import os
import re
import numpy as np
import pandas as pd
import math
from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QComboBox,
    QFrame,
    QTabWidget,
    QSizePolicy,
    QCheckBox,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

import vexis_vulkan_core
from src.gui.panels.vulkan_widget import VulkanImageWidget

class XpltLoaderThread(QThread):
    finished = Signal(object, object, object, int, list, list, str)
    progress = Signal(str)

    def __init__(self, xplt_path):
        super().__init__()
        self.xplt_path = xplt_path

    def run(self):
        try:
            self.progress.emit("Reading file with Rust parser...")
            parser = vexis_vulkan_core.XpltFastParser(self.xplt_path)
            
            self.progress.emit("Extracting geometry...")
            coords = parser.get_base_coordinates()
            num_steps = parser.get_num_steps()
            point_vars = parser.get_node_vars()
            cell_vars = parser.get_domain_vars()
            
            self.progress.emit("Triangulating elements...")
            indices = []
            d = 0
            while True:
                try:
                    elems = parser.get_domain_elements(d)
                    if not elems:
                        break
                    
                    for e in elems:
                        if len(e) == 8: # Hex8 Only currently supported for rendering
                            n = e
                            faces = [
                                (n[0], n[3], n[2]), (n[0], n[2], n[1]),
                                (n[4], n[5], n[6]), (n[4], n[6], n[7]),
                                (n[0], n[1], n[5]), (n[0], n[5], n[4]),
                                (n[1], n[2], n[6]), (n[1], n[6], n[5]),
                                (n[2], n[3], n[7]), (n[2], n[7], n[6]),
                                (n[3], n[0], n[4]), (n[3], n[4], n[7])
                            ]
                            for f in faces:
                                indices.extend(f)
                    d += 1
                except Exception:
                    break
            
            self.finished.emit(parser, coords, indices, num_steps, point_vars, cell_vars, "")
        except Exception as e:
            self.finished.emit(None, None, None, 0, [], [], str(e))


class ScalarRangeThread(QThread):
    finished = Signal(str, str, object)

    def __init__(self, parser_path, n_nodes, n_steps, scalar_name, assoc):
        super().__init__()
        self.parser_path = parser_path
        self.n_nodes = n_nodes
        self.n_steps = n_steps
        self.scalar_name = scalar_name
        self.assoc = assoc

    def run(self):
        try:
            parser = vexis_vulkan_core.XpltFastParser(self.parser_path)
            gmin = float('inf')
            gmax = float('-inf')
            found = False
            for step in range(self.n_steps):
                if self.assoc == "point":
                    raw = parser.get_node_data(step, self.scalar_name)
                    if not raw:
                        continue
                    
                    mag = []
                    if len(raw) == self.n_nodes * 3:
                        for i in range(self.n_nodes):
                            dx = raw[i*3]
                            dy = raw[i*3+1]
                            dz = raw[i*3+2]
                            mag.append(math.sqrt(dx*dx + dy*dy + dz*dz))
                    elif len(raw) >= self.n_nodes:
                        mag = raw[:self.n_nodes]
                        
                    finite = [v for v in mag if not math.isnan(v)]
                    if not finite:
                        continue
                        
                    l_min = min(finite)
                    l_max = max(finite)
                    if l_min < gmin: gmin = l_min
                    if l_max > gmax: gmax = l_max
                    found = True
            
            if found:
                if gmax <= gmin:
                    gmax = gmin + 1e-12
                self.finished.emit(self.scalar_name, self.assoc, (gmin, gmax))
            else:
                self.finished.emit(self.scalar_name, self.assoc, None)
        except Exception:
            self.finished.emit(self.scalar_name, self.assoc, None)

class ResultViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parser = None
        self.steps = []
        self.current_step_idx = 0
        self.load_thread = None
        self.current_job_name = None
        self.result_dir = None
        self.temp_dir = None
        self.xplt_path = None
        
        self.point_vars = []
        self.cell_vars = []
        
        self._active_scalar_name = None
        self._active_scalar_assoc = None
        self._active_scalar_range = None
        self._global_scalar_ranges = {}
        self.range_thread = None
        self._range_running_key = None
        self._range_pending_key = None
        
        self._is_slider_dragging = False
        self._is_updating_display = False
        self._pending_step_idx = None
        self._drag_update_interval_ms = 16

        self.theme = self._load_theme()
        self._setup_ui()

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._process_pending_update)

    @staticmethod
    def _to_bool(value, default=False):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return default

    def _load_theme(self):
        default_theme = {
            "background_top": "#1a1a2e",
            "background_bottom": "#0f0f1a",
            "legend_text_color": "#cccccc",
        }
        return default_theme

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        ctrl_layout = QHBoxLayout()
        self.job_label = QLabel("No Job Selected")
        self.job_label.setStyleSheet("font-weight: bold; font-size: 22px;")
        ctrl_layout.addWidget(self.job_label)

        ctrl_layout.addSpacing(20)
        field_label = QLabel("Field:")
        field_label.setStyleSheet("font-size: 14px;")
        ctrl_layout.addWidget(field_label)

        self.field_combo = QComboBox()
        self.field_combo.setMinimumWidth(200)
        self.field_combo.currentTextChanged.connect(self.on_field_changed)
        ctrl_layout.addWidget(self.field_combo)

        ctrl_layout.addStretch()
        layout.addLayout(ctrl_layout)

        self.tab_widget = QTabWidget()

        self.plotter_frame = QFrame()
        self.plotter_layout = QVBoxLayout(self.plotter_frame)
        self.plotter_layout.setContentsMargins(0, 0, 0, 0)
        self.plotter_layout.setSpacing(0)

        # Vulkan Widget Replacement
        self.vulkan_widget = VulkanImageWidget(self.plotter_frame)
        self.plotter_layout.addWidget(self.vulkan_widget)

        self.loading_overlay = QLabel(self.plotter_frame)
        self.loading_overlay.setAlignment(Qt.AlignCenter)
        self.loading_overlay.setStyleSheet(
            "background-color: rgba(0,0,0,200); color: white; font-size: 18px; "
            "font-weight: bold; padding: 30px; border-radius: 10px;"
        )
        self.loading_overlay.hide()
        self.tab_widget.addTab(self.plotter_frame, "3D Contour (Vulkan)")

        self.graph_frame = QFrame()
        self.graph_layout = QVBoxLayout(self.graph_frame)
        self.graph_layout.setContentsMargins(0, 0, 0, 0)
        self.graph_figure = Figure(facecolor="#0B0F14")
        self.graph_canvas = FigureCanvasQTAgg(self.graph_figure)
        self.graph_layout.addWidget(self.graph_canvas)
        self.tab_widget.addTab(self.graph_frame, "Load-Displacement Graph")
        layout.addWidget(self.tab_widget)

        time_layout = QHBoxLayout()
        self.time_label = QLabel("Time: 0.00")
        self.time_label.setFixedWidth(120)
        time_layout.addWidget(self.time_label)

        self.time_slider = QSlider(Qt.Horizontal)
        self.time_slider.setEnabled(False)
        self.time_slider.valueChanged.connect(self.on_slider_move)
        self.time_slider.sliderPressed.connect(self._on_slider_pressed)
        self.time_slider.sliderReleased.connect(self._on_slider_released)
        time_layout.addWidget(self.time_slider)

        self.step_label = QLabel("Step: 0/0")
        self.step_label.setFixedWidth(100)
        self.step_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        time_layout.addWidget(self.step_label)

        layout.addLayout(time_layout)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_overlay_geometry()

    def _update_overlay_geometry(self):
        if hasattr(self, "loading_overlay") and self.loading_overlay.isVisible():
            overlay_width = 300
            overlay_height = 80
            frame_rect = self.plotter_frame.rect()
            x = (frame_rect.width() - overlay_width) // 2
            y = (frame_rect.height() - overlay_height) // 2
            self.loading_overlay.setGeometry(x, y, overlay_width, overlay_height)
            self.loading_overlay.raise_()

    def load_result(self, job_name, result_dir, temp_dir):
        self.current_job_name = job_name
        self.result_dir = result_dir
        self.temp_dir = temp_dir
        self.job_label.setText(job_name)

        self.parser = None
        self.steps = []
        self.point_vars = []
        self.cell_vars = []
        self.field_combo.clear()
        self.time_slider.setEnabled(False)
        self._stop_range_thread()

        self._update_graph(job_name)

        base = job_name
        paths_to_check = [
            os.path.join(result_dir, f"{base}.xplt"),
            os.path.join(temp_dir, f"{base}.xplt"),
            os.path.join(os.getcwd(), "results", f"{base}.xplt"),
            os.path.join(os.getcwd(), "temp", f"{base}.xplt"),
        ]

        xplt_path = next((p for p in paths_to_check if p and os.path.exists(p)), None)

        if not xplt_path:
            return

        self.xplt_path = xplt_path
        self._show_loading_overlay("Loading Result (Rust)...")
        if self.load_thread and self.load_thread.isRunning():
            self.load_thread.terminate()
            self.load_thread.wait()

        self.load_thread = XpltLoaderThread(xplt_path)
        self.load_thread.progress.connect(self._show_loading_overlay)
        self.load_thread.finished.connect(self._on_load_finished)
        self.load_thread.start()

    def _show_loading_overlay(self, text):
        self.loading_overlay.setText(text)
        self.loading_overlay.adjustSize()
        self.loading_overlay.show()
        self._update_overlay_geometry()

    def _hide_loading_overlay(self):
        self.loading_overlay.hide()

    def _on_load_finished(self, parser, coords, indices, n_steps, point_vars, cell_vars, error_msg):
        self._hide_loading_overlay()
        if error_msg:
            print(f"Error loading xplt: {error_msg}")
            return
            
        self.parser = parser
        self.steps = [0.0] * n_steps # Could be actual times, kept simple
        self.point_vars = point_vars
        self.cell_vars = cell_vars
        
        if n_steps > 0:
            self.current_step_idx = n_steps - 1
            self.time_slider.blockSignals(True)
            self.time_slider.setRange(0, n_steps - 1)
            self.time_slider.setValue(self.current_step_idx)
            self.time_slider.setEnabled(True)
            self.time_slider.blockSignals(False)
            
        self.vulkan_widget.set_mesh_data(coords, indices)
        
        self._update_fields()
        self._update_step_labels(self.current_step_idx)
        self._queue_display_update(reset_cam=True)

    def _update_fields(self):
        self.field_combo.blockSignals(True)
        self.field_combo.clear()
        
        fields = list(self.point_vars) + list(self.cell_vars)
        priority_order = ["displacement", "Lagrange strain", "stress", "velocity"]
        sorted_fields = []
        for pf in priority_order:
            for f in fields:
                if pf.lower() in f.lower() and f not in sorted_fields:
                    sorted_fields.append(f)
        for f in fields:
            if f not in sorted_fields:
                sorted_fields.append(f)

        self.field_combo.addItems(sorted_fields)
        if sorted_fields:
            self.field_combo.setCurrentIndex(0)
        self.field_combo.blockSignals(False)

    def _update_step_labels(self, idx):
        self.time_label.setText(f"Time Step: {idx}")
        n = len(self.steps)
        self.step_label.setText(f"Step: {idx + 1}/{n if n else 0}")

    def on_slider_move(self, val):
        self.current_step_idx = val
        self._update_step_labels(val)
        self._queue_display_update()

    def _on_slider_pressed(self):
        self._is_slider_dragging = True

    def _on_slider_released(self):
        self._is_slider_dragging = False
        self._queue_display_update()

    def on_field_changed(self, _text):
        self._queue_display_update()

    def _queue_display_update(self, reset_cam=False):
        self._pending_step_idx = self.current_step_idx
        if reset_cam:
            self.vulkan_widget.zoom_level = 1.0
            self.vulkan_widget.pitch = 0.0
            self.vulkan_widget.yaw = 0.0
            
        if self._render_timer.isActive():
            return
        self._render_timer.start(self._drag_update_interval_ms)

    def _process_pending_update(self):
        if not self.parser:
            return
            
        step_idx = self._pending_step_idx
        scalar_name = self.field_combo.currentText()
        if not scalar_name:
            return
            
        assoc = "point" if scalar_name in self.point_vars else "cell"
        
        try:
            if assoc == "point":
                n_nodes = len(self.vulkan_widget.vertices_base) // 3
                mag_tuple = self.parser.get_node_scalars(step_idx, scalar_name)
                if mag_tuple:
                    mag, cmin, cmax = mag_tuple
                    
                    rng = self._request_global_scalar_range(scalar_name, assoc, n_nodes)
                    if rng:
                        cmin, cmax = rng

                    self.vulkan_widget.set_scalar_data(mag, cmin, cmax)
            else:
                # Cell variables not yet supported directly in this simple version
                pass
        except Exception as e:
            print(f"Error rendering: {e}")

    def _request_global_scalar_range(self, scalar, assoc, n_nodes):
        key = (scalar, assoc)
        if key in self._global_scalar_ranges:
            return self._global_scalar_ranges[key]

        if self.range_thread and self.range_thread.isRunning():
            return None

        self.range_thread = ScalarRangeThread(
            self.xplt_path,
            n_nodes,
            len(self.steps),
            scalar,
            assoc,
        )
        self.range_thread.finished.connect(self._on_global_scalar_range_ready)
        self.range_thread.start()
        return None

    def _on_global_scalar_range_ready(self, scalar, assoc, rng):
        if rng:
            self._global_scalar_ranges[(scalar, assoc)] = rng
            if self.field_combo.currentText() == scalar:
                self.vulkan_widget.min_val = rng[0]
                self.vulkan_widget.max_val = rng[1]
                self.vulkan_widget.update_render()
        self.range_thread = None

    def _stop_range_thread(self):
        if self.range_thread and self.range_thread.isRunning():
            self.range_thread.terminate()
            self.range_thread.wait()
            self.range_thread = None

    def _update_graph(self, job_name):
        csv_paths = [
            os.path.join(self.result_dir or "", f"{job_name}_result.csv"),
            os.path.join(os.getcwd(), "results", f"{job_name}_result.csv"),
        ]
        for csv_path in csv_paths:
            if csv_path and os.path.exists(csv_path):
                try:
                    df = pd.read_csv(csv_path)
                    if "Stroke" in df.columns and "Reaction_Force" in df.columns:
                        self._plot_graph(df, job_name)
                        return
                except:
                    pass
        self._show_no_graph_message()

    def _plot_graph(self, df, title):
        self.graph_figure.clear()
        ax = self.graph_figure.add_subplot(111)
        ax.set_facecolor("#0B0F14")
        ax.tick_params(colors="#6F8098")
        ax.plot(df["Stroke"], df["Reaction_Force"], color="#2EE7FF", linewidth=2)
        ax.set_title(title, color="#EAF2FF")
        self.graph_canvas.draw()

    def _show_no_graph_message(self):
        self.graph_figure.clear()
        ax = self.graph_figure.add_subplot(111)
        ax.set_facecolor("#0B0F14")
        ax.text(0.5, 0.5, "No graph", ha="center", va="center", color="#6F8098")
        ax.axis("off")
        self.graph_canvas.draw()

    def cleanup(self):
        if self.load_thread and self.load_thread.isRunning():
            self.load_thread.terminate()
        self._stop_range_thread()
        self._render_timer.stop()

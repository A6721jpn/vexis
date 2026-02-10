import os
import re
import numpy as np
import pandas as pd
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
from pyvistaqt import QtInteractor

# Matplotlib Qt backend for embedded graphs
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from src.utils.xplt_loader import WaffleironLoader


class XpltLoaderThread(QThread):
    """Background thread for loading .xplt files."""

    finished = Signal(object, str)  # loader, error_message
    progress = Signal(str)

    def __init__(self, xplt_path):
        super().__init__()
        self.xplt_path = xplt_path

    def run(self):
        try:
            self.progress.emit("Reading file...")
            loader = WaffleironLoader(self.xplt_path)
            if loader.get_time_steps():
                self.progress.emit("Caching step data...")
                loader.preload_steps(progress_callback=self.progress.emit)
            self.finished.emit(loader, "")
        except Exception as e:
            self.finished.emit(None, str(e))


class ResultViewer(QWidget):
    """
    Result viewer with tabbed display:
    - Tab 1: 3D Contour (PyVista)
    - Tab 2: Graph (matplotlib)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loader = None
        self.grid = None
        self.steps = []
        self.current_step_idx = 0
        self.load_thread = None
        self.current_job_name = None
        self.result_dir = None
        self.temp_dir = None

        # Rendering state
        self.base_points = None
        self.render_mesh = None
        self.mesh_actor = None
        self.edge_actor = None
        self._active_scalar_name = None
        self._active_scalar_assoc = None  # "point" | "cell" | None
        self._last_edges_step = None
        self._is_slider_dragging = False
        self._is_updating_display = False
        self._pending_step_idx = None
        self._pending_reset_cam = False
        self._pending_high_quality = True
        self._drag_update_interval_ms = 16  # ~60fps max

        # Load theme
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
        """Load viewer theme from QSS file's special comment block."""
        default_theme = {
            "background_top": "#1a1a2e",
            "background_bottom": "#0f0f1a",
            "legend_text_color": "#cccccc",
            "legend_title_size": 18,
            "legend_label_size": 14,
            "edge_color": "#333333",
            "colormap": "turbo",
            "show_edges": False,
        }

        qss_paths = [
            os.path.join(os.getcwd(), "src", "gui", "styles", "dark_theme.qss"),
            os.path.join(os.path.dirname(__file__), "..", "styles", "dark_theme.qss"),
        ]

        for qss_path in qss_paths:
            if not os.path.exists(qss_path):
                continue
            try:
                with open(qss_path, "r", encoding="utf-8") as f:
                    content = f.read()
                match = re.search(
                    r"@PYVISTA_THEME_START\s*(.*?)\s*@PYVISTA_THEME_END",
                    content,
                    re.DOTALL,
                )
                if not match:
                    continue
                theme_block = match.group(1)
                for line in theme_block.strip().split("\n"):
                    line = line.strip()
                    if ":" not in line or line.startswith("#"):
                        continue
                    key, value = line.split(":", 1)
                    key = key.strip()
                    value = value.strip()
                    if value.isdigit():
                        value = int(value)
                    default_theme[key] = value
                break
            except Exception as e:
                print(f"Theme load error: {e}")

        return default_theme

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Top Control Bar
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
        self.field_combo.setStyleSheet("font-size: 14px;")
        self.field_combo.currentTextChanged.connect(self.on_field_changed)
        ctrl_layout.addWidget(self.field_combo)

        self.edge_checkbox = QCheckBox("Mesh Edges")
        self.edge_checkbox.setStyleSheet("font-size: 13px;")
        self.edge_checkbox.setChecked(self._to_bool(self.theme.get("show_edges", False)))
        self.edge_checkbox.toggled.connect(self._on_edge_toggled)
        ctrl_layout.addWidget(self.edge_checkbox)

        ctrl_layout.addStretch()
        layout.addLayout(ctrl_layout)

        # Tab Widget for 3D and Graph views
        self.tab_widget = QTabWidget()

        # --- Tab 1: 3D Contour ---
        self.plotter_frame = QFrame()
        self.plotter_layout = QVBoxLayout(self.plotter_frame)
        self.plotter_layout.setContentsMargins(0, 0, 0, 0)
        self.plotter_layout.setSpacing(0)

        self.plotter = QtInteractor(self.plotter_frame)
        self._apply_plotter_theme()
        self.plotter_layout.addWidget(self.plotter)

        self.loading_overlay = QLabel(self.plotter_frame)
        self.loading_overlay.setAlignment(Qt.AlignCenter)
        self.loading_overlay.setStyleSheet(
            "background-color: rgba(0,0,0,200); color: white; font-size: 18px; "
            "font-weight: bold; padding: 30px; border-radius: 10px;"
        )
        self.loading_overlay.hide()

        self.tab_widget.addTab(self.plotter_frame, "3D Contour")

        # --- Tab 2: Graph ---
        self.graph_frame = QFrame()
        self.graph_layout = QVBoxLayout(self.graph_frame)
        self.graph_layout.setContentsMargins(0, 0, 0, 0)

        self.graph_figure = Figure(facecolor="#0B0F14")
        self.graph_canvas = FigureCanvasQTAgg(self.graph_figure)
        self.graph_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.graph_layout.addWidget(self.graph_canvas)

        self.tab_widget.addTab(self.graph_frame, "Load-Displacement Graph")
        layout.addWidget(self.tab_widget)

        # Time Slider & Info
        time_layout = QHBoxLayout()

        self.time_label = QLabel("Time: 0.00")
        self.time_label.setFixedWidth(120)
        time_layout.addWidget(self.time_label)

        self.time_slider = QSlider(Qt.Horizontal)
        self.time_slider.setEnabled(False)
        self.time_slider.setTracking(True)
        self.time_slider.valueChanged.connect(self.on_slider_move)
        self.time_slider.sliderPressed.connect(self._on_slider_pressed)
        self.time_slider.sliderReleased.connect(self._on_slider_released)
        time_layout.addWidget(self.time_slider)

        self.step_label = QLabel("Step: 0/0")
        self.step_label.setFixedWidth(100)
        self.step_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        time_layout.addWidget(self.step_label)

        layout.addLayout(time_layout)

    def _apply_plotter_theme(self):
        """Apply theme colors to PyVista plotter."""
        bg_top = self.theme.get("background_top", "#1a1a2e")
        bg_bottom = self.theme.get("background_bottom", "#0f0f1a")
        self.plotter.set_background(bg_bottom, top=bg_top)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_overlay_geometry()

    def _update_overlay_geometry(self):
        """Update loading overlay position and size."""
        if hasattr(self, "loading_overlay") and self.loading_overlay.isVisible():
            overlay_width = 250
            overlay_height = 80
            frame_rect = self.plotter_frame.rect()
            x = (frame_rect.width() - overlay_width) // 2
            y = (frame_rect.height() - overlay_height) // 2
            self.loading_overlay.setGeometry(x, y, overlay_width, overlay_height)
            self.loading_overlay.raise_()

    def _reset_display_state(self):
        self.base_points = None
        self.render_mesh = None
        self.mesh_actor = None
        self.edge_actor = None
        self._active_scalar_name = None
        self._active_scalar_assoc = None
        self._last_edges_step = None
        self._is_slider_dragging = False
        self._is_updating_display = False
        self._pending_step_idx = None
        self._pending_reset_cam = False
        self._pending_high_quality = True
        self._render_timer.stop()

    def _clear_plotter(self):
        self.plotter.clear()
        self._apply_plotter_theme()

    def load_result(self, job_name, result_dir, temp_dir):
        """Load result for a job."""
        self.current_job_name = job_name
        self.result_dir = result_dir
        self.temp_dir = temp_dir
        self.job_label.setText(job_name)

        self._reset_display_state()
        self._clear_plotter()

        self.loader = None
        self.grid = None
        self.steps = []
        self.field_combo.clear()
        self.time_slider.setEnabled(False)
        self.time_label.setText("Time: 0.00")
        self.step_label.setText("Step: 0/0")

        self._update_graph(job_name)

        base = job_name
        paths_to_check = [
            os.path.join(result_dir, f"{base}.xplt"),
            os.path.join(temp_dir, f"{base}.xplt"),
            os.path.join(os.getcwd(), "results", f"{base}.xplt"),
            os.path.join(os.getcwd(), "temp", f"{base}.xplt"),
        ]

        xplt_path = None
        for p in paths_to_check:
            if p and os.path.exists(p):
                xplt_path = p
                break

        if not xplt_path:
            self.plotter.add_text("No .xplt file found", position="upper_left", color="white")
            return

        self._show_loading_overlay("Loading Result...")
        self._stop_loading_thread()

        self.load_thread = XpltLoaderThread(xplt_path)
        self.load_thread.progress.connect(self._show_loading_overlay)
        self.load_thread.finished.connect(self._on_load_finished)
        self.load_thread.start()

    def _show_loading_overlay(self, text):
        """Show loading overlay with specified text."""
        self.loading_overlay.setText(text)
        self.loading_overlay.adjustSize()
        self.loading_overlay.show()
        self._update_overlay_geometry()

    def _hide_loading_overlay(self):
        """Hide loading overlay."""
        self.loading_overlay.hide()

    def _update_graph(self, job_name):
        """Load CSV data and plot graph directly in the canvas."""
        csv_paths = [
            os.path.join(self.result_dir or "", f"{job_name}_result.csv"),
            os.path.join(os.getcwd(), "results", f"{job_name}_result.csv"),
        ]

        for csv_path in csv_paths:
            if not (csv_path and os.path.exists(csv_path)):
                continue
            try:
                df = pd.read_csv(csv_path)
                if "Stroke" in df.columns and "Reaction_Force" in df.columns:
                    self._plot_graph(df, job_name)
                    return
            except Exception as e:
                print(f"Error loading CSV: {e}")

        self._show_no_graph_message()

    def _plot_graph(self, df, title):
        """Plot Force-Stroke graph on the embedded canvas."""
        self.graph_figure.clear()
        ax = self.graph_figure.add_subplot(111)

        ax.set_facecolor("#0B0F14")
        ax.tick_params(colors="#6F8098")
        ax.spines["bottom"].set_color("#243244")
        ax.spines["top"].set_color("#243244")
        ax.spines["left"].set_color("#243244")
        ax.spines["right"].set_color("#243244")
        ax.xaxis.label.set_color("#EAF2FF")
        ax.yaxis.label.set_color("#EAF2FF")
        ax.title.set_color("#EAF2FF")

        ax.plot(
            df["Stroke"],
            df["Reaction_Force"],
            marker="o",
            color="#2EE7FF",
            markeredgecolor="white",
            markersize=4,
            linewidth=2,
            label="KEYCAP Reaction",
        )

        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.set_xlabel("Stroke (mm)", fontsize=10)
        ax.set_ylabel("Reaction Force (N)", fontsize=10)
        ax.grid(True, linestyle="--", alpha=0.5, color="#243244")
        ax.legend(facecolor="#141E2A", edgecolor="#243244", labelcolor="#EAF2FF")

        self.graph_figure.tight_layout()
        self.graph_canvas.draw()

    def _show_no_graph_message(self):
        """Display 'no graph' message on the canvas."""
        self.graph_figure.clear()
        ax = self.graph_figure.add_subplot(111)
        ax.set_facecolor("#0B0F14")
        ax.text(
            0.5,
            0.5,
            "No graph available\n(Graph will be generated after analysis)",
            ha="center",
            va="center",
            fontsize=12,
            color="#6F8098",
            transform=ax.transAxes,
        )
        ax.axis("off")
        self.graph_canvas.draw()

    def _stop_loading_thread(self):
        if self.load_thread and self.load_thread.isRunning():
            self.load_thread.terminate()
            self.load_thread.wait()
            return True
        return False

    def _on_load_finished(self, loader, error_msg):
        self._hide_loading_overlay()
        if error_msg:
            self._clear_plotter()
            self.plotter.add_text(f"Error: {error_msg}", position="upper_left", color="red")
            return
        if not loader:
            return

        self.loader = loader
        try:
            self.grid = self.loader.get_mesh()
            self.steps = self.loader.get_time_steps()

            if self.steps:
                self.current_step_idx = len(self.steps) - 1
                self.time_slider.blockSignals(True)
                self.time_slider.setRange(0, len(self.steps) - 1)
                self.time_slider.setValue(self.current_step_idx)
                self.time_slider.setEnabled(True)
                self.time_slider.blockSignals(False)
            else:
                self.current_step_idx = 0

            self.loader.load_step_result(self.grid, self.current_step_idx)
            self._update_fields()
            self.base_points = np.array(self.grid.points, copy=True)
            self.render_mesh = self.grid.copy(deep=True)
            self._update_step_labels(self.current_step_idx)

            self._queue_display_update(
                step_idx=self.current_step_idx,
                reset_cam=True,
                high_quality=True,
            )
        except Exception as e:
            self._clear_plotter()
            self.plotter.add_text(f"Parse Error: {e}", position="upper_left", color="red")

    def _update_fields(self):
        """Populate field dropdown with available data fields."""
        if not self.grid:
            return

        self.field_combo.blockSignals(True)
        self.field_combo.clear()

        fields = []
        for k in self.grid.point_data.keys():
            fields.append(k)
        for k in self.grid.cell_data.keys():
            if k not in fields:
                fields.append(k)

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
        if not self.steps:
            self.time_label.setText("Time: 0.00")
            self.step_label.setText("Step: 0/0")
            return
        idx = max(0, min(idx, len(self.steps) - 1))
        t = self.steps[idx]
        self.time_label.setText(f"Time: {t:.4f}")
        self.step_label.setText(f"Step: {idx + 1}/{len(self.steps)}")

    def _on_slider_pressed(self):
        self._is_slider_dragging = True

    def _on_slider_released(self):
        self._is_slider_dragging = False
        self._queue_display_update(
            step_idx=self.current_step_idx,
            reset_cam=False,
            high_quality=True,
        )

    def _on_edge_toggled(self, _checked):
        if not self.grid:
            return
        self._queue_display_update(
            step_idx=self.current_step_idx,
            reset_cam=False,
            high_quality=True,
        )

    def on_slider_move(self, val):
        self.current_step_idx = val
        self._update_step_labels(val)

        self._queue_display_update(
            step_idx=val,
            reset_cam=False,
            high_quality=not self._is_slider_dragging,
        )

    def on_field_changed(self, _text):
        if not self.grid:
            return
        self._queue_display_update(
            step_idx=self.current_step_idx,
            reset_cam=False,
            high_quality=True,
        )

    def _queue_display_update(self, step_idx=None, reset_cam=False, high_quality=True):
        if step_idx is not None:
            self._pending_step_idx = step_idx
        self._pending_reset_cam = self._pending_reset_cam or reset_cam
        self._pending_high_quality = self._pending_high_quality or high_quality

        if self._render_timer.isActive():
            if high_quality:
                self._render_timer.stop()
                self._render_timer.start(0)
            return

        interval = 0 if high_quality else self._drag_update_interval_ms
        self._render_timer.start(interval)

    def _process_pending_update(self):
        if self._is_updating_display:
            self._render_timer.start(self._drag_update_interval_ms)
            return

        if self._pending_step_idx is None:
            return

        step_idx = self._pending_step_idx
        reset_cam = self._pending_reset_cam
        high_quality = self._pending_high_quality

        self._pending_step_idx = None
        self._pending_reset_cam = False
        self._pending_high_quality = False

        self._is_updating_display = True
        try:
            self.current_step_idx = step_idx
            self._update_display(reset_cam=reset_cam, high_quality=high_quality)
        finally:
            self._is_updating_display = False

        if self._pending_step_idx is not None:
            next_interval = 0 if self._pending_high_quality else self._drag_update_interval_ms
            self._render_timer.start(next_interval)

    def _resolve_scalar(self):
        scalar = self.field_combo.currentText() or None
        if not scalar:
            return None, None
        if scalar in self.grid.point_data:
            return scalar, "point"
        if scalar in self.grid.cell_data:
            return scalar, "cell"
        return None, None

    def _apply_displacement_to_render_mesh(self):
        if self.render_mesh is None or self.base_points is None:
            return

        points = self.base_points
        if "displacement" in self.grid.point_data:
            disp = np.asarray(self.grid.point_data["displacement"])
            if (
                disp.ndim == 2
                and disp.shape[0] == self.base_points.shape[0]
                and disp.shape[1] >= 3
            ):
                with np.errstate(all="ignore"):
                    points = self.base_points + disp[:, :3]
        self.render_mesh.points = points

    def _update_active_scalar_array(self, scalar, assoc):
        if not scalar or not assoc:
            return False
        if assoc == "point":
            if scalar not in self.grid.point_data:
                return False
            self.render_mesh.point_data[scalar] = np.asarray(self.grid.point_data[scalar])
        else:
            if scalar not in self.grid.cell_data:
                return False
            self.render_mesh.cell_data[scalar] = np.asarray(self.grid.cell_data[scalar])
        self.render_mesh.set_active_scalars(scalar, preference=assoc)
        return True

    def _scalar_bar_args(self, scalar):
        return {
            "title": scalar or "",
            "title_font_size": self.theme.get("legend_title_size", 18),
            "label_font_size": self.theme.get("legend_label_size", 14),
            "color": self.theme.get("legend_text_color", "#cccccc"),
            "font_family": "arial",
        }

    def _rebuild_mesh_actor(self, scalar, assoc, reset_cam=False):
        cam = self.plotter.camera_position if (self.mesh_actor and not reset_cam) else None

        self.plotter.remove_actor("result_mesh", reset_camera=False, render=False)
        self.plotter.remove_actor("result_edges", reset_camera=False, render=False)
        self.plotter.remove_actor("scalar_warning", reset_camera=False, render=False)

        cmap = self.theme.get("colormap", "turbo")
        if scalar and assoc:
            self.mesh_actor = self.plotter.add_mesh(
                self.render_mesh,
                scalars=scalar,
                cmap=cmap,
                show_edges=False,
                scalar_bar_args=self._scalar_bar_args(scalar),
                name="result_mesh",
                render=False,
            )
        else:
            self.mesh_actor = self.plotter.add_mesh(
                self.render_mesh,
                color="lightblue",
                show_edges=False,
                name="result_mesh",
                render=False,
            )
            self.plotter.add_text(
                "No scalar data for selected field",
                position="upper_left",
                color="white",
                name="scalar_warning",
            )

        if cam:
            self.plotter.camera_position = cam
        elif reset_cam:
            self.plotter.reset_camera()

        self._active_scalar_name = scalar
        self._active_scalar_assoc = assoc
        self._last_edges_step = None

    def _update_edges_actor(self, high_quality):
        wants_edges = bool(self.edge_checkbox.isChecked()) and high_quality
        if not wants_edges:
            self.plotter.remove_actor("result_edges", reset_camera=False, render=False)
            self._last_edges_step = None
            self.edge_actor = None
            return

        if self._last_edges_step == self.current_step_idx and self.edge_actor is not None:
            return

        edge_color = self.theme.get("edge_color", "#333333")
        edges = self.render_mesh.extract_all_edges()
        self.edge_actor = self.plotter.add_mesh(
            edges,
            color=edge_color,
            line_width=0.5,
            name="result_edges",
            render=False,
        )
        self._last_edges_step = self.current_step_idx

    def _update_display(self, reset_cam=False, high_quality=True):
        """Update 3D display with current step and field."""
        if not self.loader or self.grid is None:
            return

        try:
            self.loader.load_step_result(self.grid, self.current_step_idx)
            self._update_step_labels(self.current_step_idx)

            if self.render_mesh is None:
                self.render_mesh = self.grid.copy(deep=True)

            self._apply_displacement_to_render_mesh()
            scalar, assoc = self._resolve_scalar()

            rebuild_actor = (
                self.mesh_actor is None
                or scalar != self._active_scalar_name
                or assoc != self._active_scalar_assoc
            )

            if scalar and assoc:
                self._update_active_scalar_array(scalar, assoc)

            if rebuild_actor:
                self._rebuild_mesh_actor(scalar, assoc, reset_cam=reset_cam)
            elif reset_cam:
                self.plotter.reset_camera()

            self._update_edges_actor(high_quality=high_quality)
            self.plotter.render()
        except Exception as e:
            print(f"Display Error: {e}")

    def cleanup(self):
        """Cleanup resources."""
        self._stop_loading_thread()
        self._render_timer.stop()
        try:
            self.plotter.close()
        except Exception:
            pass

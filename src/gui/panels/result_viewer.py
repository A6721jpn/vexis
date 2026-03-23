import os
import re
import numpy as np
import pandas as pd
import pyvista as pv
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
            self.finished.emit(loader, "")
        except Exception as e:
            self.finished.emit(None, str(e))


class ScalarRangeThread(QThread):
    """Background thread for computing global scalar range across all steps."""

    finished = Signal(str, str, object)  # scalar_name, assoc, (min,max)|None

    def __init__(self, loader, n_steps, scalar_name, assoc):
        super().__init__()
        self.loader = loader
        self.n_steps = n_steps
        self.scalar_name = scalar_name
        self.assoc = assoc

    @staticmethod
    def _to_scalar_magnitude(values):
        arr = np.asarray(values, dtype=float)
        if arr.ndim == 1:
            return arr
        if arr.shape[0] == 0:
            return np.asarray([], dtype=float)
        flat = arr.reshape(arr.shape[0], -1)
        with np.errstate(all="ignore"):
            return np.linalg.norm(flat, axis=1)

    def run(self):
        gmin = np.inf
        gmax = -np.inf
        found = False

        for step_idx in range(self.n_steps):
            cached = self.loader.get_cached_step(step_idx)
            if self.assoc == "point":
                raw = cached["point"].get(self.scalar_name)
                if raw is None:
                    continue
                point_values = self._to_scalar_magnitude(raw)
            else:
                raw = cached["cell"].get(self.scalar_name)
                if raw is None:
                    continue
                cell_values = self._to_scalar_magnitude(raw)
                point_values = self.loader.domain_scalar_to_point(cell_values)

            finite = np.asarray(point_values, dtype=float).reshape(-1)
            finite = finite[np.isfinite(finite)]
            if finite.size == 0:
                continue

            local_min = float(np.min(finite))
            local_max = float(np.max(finite))
            if local_min < gmin:
                gmin = local_min
            if local_max > gmax:
                gmax = local_max
            found = True

        if not found:
            rng = None
        else:
            if gmax <= gmin:
                gmax = gmin + 1e-12
            rng = (gmin, gmax)
        self.finished.emit(self.scalar_name, self.assoc, rng)


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
        self.surface_edge_point_ids = None
        self.surface_edge_mesh = None
        self._active_scalar_name = None
        self._active_scalar_assoc = None  # "point" | "cell" | None
        self._active_scalar_range = None
        self._global_scalar_ranges = {}
        self.range_thread = None
        self._range_running_key = None
        self._range_pending_key = None
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
            "show_edges": True,
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
        self._stop_range_thread()
        self.base_points = None
        self.render_mesh = None
        self.mesh_actor = None
        self.edge_actor = None
        self.surface_edge_point_ids = None
        self.surface_edge_mesh = None
        self._active_scalar_name = None
        self._active_scalar_assoc = None
        self._active_scalar_range = None
        self._global_scalar_ranges = {}
        self._range_running_key = None
        self._range_pending_key = None
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

    def _stop_range_thread(self):
        if self.range_thread and self.range_thread.isRunning():
            self.range_thread.terminate()
            self.range_thread.wait()
            self.range_thread = None
            self._range_running_key = None
            self._range_pending_key = None
            return True
        self.range_thread = None
        self._range_running_key = None
        self._range_pending_key = None
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
            raw_lines = self.loader.get_surface_edge_lines()
            if raw_lines.size > 0:
                edge_pairs = raw_lines.reshape(-1, 3)[:, 1:3]
                used_ids = np.unique(edge_pairs.reshape(-1))

                remap = np.full(self.base_points.shape[0], -1, dtype=np.int64)
                remap[used_ids] = np.arange(used_ids.shape[0], dtype=np.int64)
                compact_pairs = remap[edge_pairs]

                compact_lines = np.empty(compact_pairs.shape[0] * 3, dtype=np.int64)
                compact_lines[0::3] = 2
                compact_lines[1::3] = compact_pairs[:, 0]
                compact_lines[2::3] = compact_pairs[:, 1]

                self.surface_edge_point_ids = used_ids
                self.surface_edge_mesh = pv.PolyData(
                    np.array(self.base_points[self.surface_edge_point_ids], copy=True)
                )
                self.surface_edge_mesh.lines = compact_lines
            else:
                self.surface_edge_point_ids = None
                self.surface_edge_mesh = None
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
        if self.surface_edge_mesh is not None and self.surface_edge_point_ids is not None:
            self.surface_edge_mesh.points = np.array(
                points[self.surface_edge_point_ids],
                copy=True,
            )

    def _to_scalar_magnitude(self, values):
        """Convert scalar/vector/tensor array to 1D magnitude for stable contour coloring."""
        arr = np.asarray(values, dtype=float)
        if arr.ndim == 1:
            return arr
        if arr.shape[0] == 0:
            return np.asarray([], dtype=float)
        flat = arr.reshape(arr.shape[0], -1)
        with np.errstate(all="ignore"):
            return np.linalg.norm(flat, axis=1)

    @staticmethod
    def _finite_range(values):
        arr = np.asarray(values, dtype=float).reshape(-1)
        if arr.size == 0:
            return None
        finite = arr[np.isfinite(arr)]
        if finite.size == 0:
            return None
        vmin = float(np.min(finite))
        vmax = float(np.max(finite))
        if vmax <= vmin:
            vmax = vmin + 1e-12
        return (vmin, vmax)

    def _request_global_scalar_range(self, scalar, assoc):
        """Start asynchronous global range computation for selected scalar."""
        if not scalar or not assoc or not self.loader or not self.steps:
            return
        key = (scalar, assoc)
        if key in self._global_scalar_ranges:
            return

        if self.range_thread and self.range_thread.isRunning():
            if self._range_running_key == key:
                return
            self._range_pending_key = key
            return

        self._range_running_key = key
        self._range_pending_key = None
        self.range_thread = ScalarRangeThread(
            self.loader,
            len(self.steps),
            scalar,
            assoc,
        )
        self.range_thread.finished.connect(self._on_global_scalar_range_ready)
        self.range_thread.start()

    def _on_global_scalar_range_ready(self, scalar, assoc, rng):
        key = (scalar, assoc)
        self._global_scalar_ranges[key] = rng
        self._range_running_key = None
        self.range_thread = None

        if (
            self._active_scalar_name == scalar
            and self._active_scalar_assoc == assoc
            and self.mesh_actor is not None
            and rng is not None
        ):
            self._active_scalar_range = rng
            try:
                self.mesh_actor.mapper.scalar_range = rng
                self.plotter.render()
            except Exception:
                pass

        if self._range_pending_key and self._range_pending_key not in self._global_scalar_ranges:
            next_key = self._range_pending_key
            self._range_pending_key = None
            self._request_global_scalar_range(next_key[0], next_key[1])

    def _update_active_scalar_array(self, scalar, assoc):
        if not scalar or not assoc:
            return False

        if assoc == "point":
            if scalar not in self.grid.point_data:
                return False
            point_values = self._to_scalar_magnitude(self.grid.point_data[scalar])
        else:
            if scalar not in self.grid.cell_data:
                return False
            cell_values = self._to_scalar_magnitude(self.grid.cell_data[scalar])
            point_values = self.loader.domain_scalar_to_point(cell_values)

        self.render_mesh.point_data["_active_scalar"] = point_values
        self.render_mesh.set_active_scalars("_active_scalar", preference="point")
        self._active_scalar_range = self._global_scalar_ranges.get((scalar, assoc))
        if self._active_scalar_range is None:
            self._active_scalar_range = self._finite_range(point_values)
        self._request_global_scalar_range(scalar, assoc)

        if self.mesh_actor is not None and self._active_scalar_range is not None:
            try:
                self.mesh_actor.mapper.scalar_range = self._active_scalar_range
            except Exception:
                pass
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
        self.plotter.remove_actor("scalar_warning", reset_camera=False, render=False)

        cmap = self.theme.get("colormap", "turbo")
        if scalar and assoc:
            self.mesh_actor = self.plotter.add_mesh(
                self.render_mesh,
                scalars="_active_scalar",
                cmap=cmap,
                show_edges=False,
                clim=self._active_scalar_range,
                scalar_bar_args=self._scalar_bar_args(scalar),
                name="result_mesh",
                reset_camera=False,
                render=False,
            )
        else:
            self.mesh_actor = self.plotter.add_mesh(
                self.render_mesh,
                color="lightblue",
                show_edges=False,
                name="result_mesh",
                reset_camera=False,
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

    def _update_surface_edge_actor(self, show_edges):
        if not show_edges or self.surface_edge_mesh is None:
            if self.edge_actor is not None:
                self.plotter.remove_actor("result_edges", reset_camera=False, render=False)
                self.edge_actor = None
            return

        if self.edge_actor is None:
            edge_color = self.theme.get("edge_color", "#333333")
            self.edge_actor = self.plotter.add_mesh(
                self.surface_edge_mesh,
                color=edge_color,
                line_width=0.5,
                render_points_as_spheres=False,
                render_lines_as_tubes=False,
                lighting=False,
                pickable=False,
                name="result_edges",
                reset_camera=False,
                render=False,
            )
            try:
                self.edge_actor.prop.render_points_as_spheres = False
                self.edge_actor.prop.point_size = 1
                self.edge_actor.prop.lighting = False
                self.edge_actor.GetProperty().SetVertexVisibility(0)
            except Exception:
                pass

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
            show_edges = bool(self.edge_checkbox.isChecked()) and high_quality

            rebuild_actor = (
                self.mesh_actor is None
                or scalar != self._active_scalar_name
                or assoc != self._active_scalar_assoc
            )

            has_scalar = False
            if scalar and assoc:
                has_scalar = self._update_active_scalar_array(scalar, assoc)

            if not has_scalar:
                rebuild_actor = rebuild_actor or (self._active_scalar_name is not None)
                scalar = None
                assoc = None
                self._active_scalar_range = None

            if rebuild_actor:
                self._rebuild_mesh_actor(
                    scalar,
                    assoc,
                    reset_cam=reset_cam,
                )
            elif reset_cam:
                self.plotter.reset_camera()

            self._update_surface_edge_actor(show_edges)
            self.plotter.render()
        except Exception as e:
            print(f"Display Error: {e}")

    def cleanup(self):
        """Cleanup resources."""
        self._stop_loading_thread()
        self._stop_range_thread()
        self._render_timer.stop()
        try:
            self.plotter.close()
        except Exception:
            pass

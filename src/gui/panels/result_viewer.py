import os
import yaml
import pyvista as pv
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                               QLabel, QSlider, QComboBox, QFrame, QTabWidget,
                               QScrollArea, QSizePolicy)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QPixmap
from pyvistaqt import QtInteractor
import numpy as np

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


class ResultViewer(QWidget):
    """
    Result viewer with tabbed display:
    - Tab 1: 3D Contour (PyVista)
    - Tab 2: Graph (PNG image)
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
        
        # Load theme
        self.theme = self._load_theme()
        
        self._setup_ui()

    def _load_theme(self):
        """Load viewer theme from QSS file's special comment block."""
        default_theme = {
            "background_top": "#1a1a2e",
            "background_bottom": "#0f0f1a",
            "legend_text_color": "#cccccc",
            "legend_title_size": 18,
            "legend_label_size": 14,
            "edge_color": "#333333",
            "colormap": "turbo"
        }
        
        # Try to load from QSS file
        qss_paths = [
            os.path.join(os.getcwd(), "src", "gui", "styles", "dark_theme.qss"),
            os.path.join(os.path.dirname(__file__), "..", "styles", "dark_theme.qss"),
        ]
        
        for qss_path in qss_paths:
            if os.path.exists(qss_path):
                try:
                    with open(qss_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    
                    # Parse @PYVISTA_THEME_START ... @PYVISTA_THEME_END block
                    import re
                    match = re.search(r'@PYVISTA_THEME_START\s*(.*?)\s*@PYVISTA_THEME_END', content, re.DOTALL)
                    if match:
                        theme_block = match.group(1)
                        for line in theme_block.strip().split('\n'):
                            line = line.strip()
                            if ':' in line and not line.startswith('#'):
                                key, value = line.split(':', 1)
                                key = key.strip()
                                value = value.strip()
                                # Convert numeric values
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
        
        # Field Selector (next to job name on left)
        ctrl_layout.addSpacing(20)
        field_label = QLabel("Field:")
        field_label.setStyleSheet("font-size: 14px;")
        ctrl_layout.addWidget(field_label)
        self.field_combo = QComboBox()
        self.field_combo.setMinimumWidth(200)
        self.field_combo.setStyleSheet("font-size: 14px;")
        self.field_combo.currentTextChanged.connect(self.on_field_changed)
        ctrl_layout.addWidget(self.field_combo)
        
        ctrl_layout.addStretch()

        layout.addLayout(ctrl_layout)

        # Tab Widget for 3D and Graph views
        self.tab_widget = QTabWidget()
        
        # --- Tab 1: 3D Contour ---
        self.plotter_frame = QFrame()
        self.plotter_layout = QVBoxLayout(self.plotter_frame)
        self.plotter_layout.setContentsMargins(0, 0, 0, 0)
        
        self.plotter = QtInteractor(self.plotter_frame)
        self._apply_plotter_theme()
        self.plotter_layout.addWidget(self.plotter)
        
        self.tab_widget.addTab(self.plotter_frame, "3D Contour")
        
        # --- Tab 2: Graph ---
        self.graph_scroll = QScrollArea()
        self.graph_scroll.setWidgetResizable(True)
        self.graph_scroll.setAlignment(Qt.AlignCenter)
        
        self.graph_label = QLabel("No graph available")
        self.graph_label.setAlignment(Qt.AlignCenter)
        self.graph_label.setStyleSheet("background-color: #1a1a2e;")
        self.graph_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.graph_scroll.setWidget(self.graph_label)
        
        self.tab_widget.addTab(self.graph_scroll, "Load-Displacement Graph")
        
        layout.addWidget(self.tab_widget)

        # Time Slider & Info
        time_layout = QHBoxLayout()
        
        self.time_label = QLabel("Time: 0.00")
        self.time_label.setFixedWidth(120)
        time_layout.addWidget(self.time_label)

        self.time_slider = QSlider(Qt.Horizontal)
        self.time_slider.setEnabled(False)
        self.time_slider.valueChanged.connect(self.on_slider_move)
        time_layout.addWidget(self.time_slider)
        
        self.step_label = QLabel("Step: 0/0")
        self.step_label.setFixedWidth(100)
        self.step_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        time_layout.addWidget(self.step_label)

        layout.addLayout(time_layout)

        # Loading Overlay
        self.loading_overlay = QLabel("Loading...", self.plotter)
        self.loading_overlay.setAlignment(Qt.AlignCenter)
        self.loading_overlay.setStyleSheet(
            "background-color: rgba(0,0,0,180); color: white; font-size: 16px; padding: 20px;"
        )
        self.loading_overlay.hide()

    def _apply_plotter_theme(self):
        """Apply theme colors to PyVista plotter."""
        bg_top = self.theme.get("background_top", "#1a1a2e")
        bg_bottom = self.theme.get("background_bottom", "#0f0f1a")
        
        # Set gradient background
        self.plotter.set_background(bg_bottom, top=bg_top)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'loading_overlay'):
            self.loading_overlay.resize(self.plotter.size())

    def load_result(self, job_name, result_dir, temp_dir):
        """Load result for a job."""
        self.current_job_name = job_name
        self.result_dir = result_dir
        self.temp_dir = temp_dir
        self.job_label.setText(job_name)
        
        # Clear previous
        self.plotter.clear()
        self._apply_plotter_theme()
        self.loader = None
        self.grid = None
        self.steps = []
        self.field_combo.clear()
        self.time_slider.setEnabled(False)
        self.time_label.setText("Time: 0.00")
        self.step_label.setText("Step: 0/0")
        
        # Load graph PNG
        self._load_graph_png(job_name)
        
        # Find xplt file
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
            self.plotter.add_text("No .xplt file found", position='upper_left', color='white')
            return

        # Start loading thread
        self.loading_overlay.setText("Loading Result...")
        self.loading_overlay.show()
        
        self._stop_loading_thread()

        self.load_thread = XpltLoaderThread(xplt_path)
        self.load_thread.finished.connect(self._on_load_finished)
        self.load_thread.start()

    def _load_graph_png(self, job_name):
        """Load graph PNG for the job."""
        graph_paths = [
            os.path.join(self.result_dir or "", f"{job_name}_graph.png"),
            os.path.join(os.getcwd(), "results", f"{job_name}_graph.png"),
        ]
        
        for graph_path in graph_paths:
            if graph_path and os.path.exists(graph_path):
                pixmap = QPixmap(graph_path)
                if not pixmap.isNull():
                    # Scale to fit while maintaining aspect ratio
                    scaled = pixmap.scaled(800, 600, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self.graph_label.setPixmap(scaled)
                    return
        
        self.graph_label.setText("No graph available\n(Graph will be generated after analysis)")
        self.graph_label.setPixmap(QPixmap())

    def _stop_loading_thread(self):
        if self.load_thread and self.load_thread.isRunning():
            self.load_thread.terminate()
            self.load_thread.wait()
            return True
        return False

    def _on_load_finished(self, loader, error_msg):
        self.loading_overlay.hide()
        if error_msg:
            self.plotter.add_text(f"Error: {error_msg}", position='upper_left', color='red')
            return
            
        if not loader:
            return

        self.loader = loader
        
        try:
            self.grid = self.loader.get_mesh()
            self.steps = self.loader.get_time_steps()
            
            # Setup slider
            if self.steps:
                self.time_slider.blockSignals(True)
                self.time_slider.setRange(0, len(self.steps) - 1)
                self.time_slider.setValue(len(self.steps) - 1)
                self.time_slider.setEnabled(True)
                self.time_slider.blockSignals(False)
                self.current_step_idx = len(self.steps) - 1
            
            # IMPORTANT: Load step data BEFORE populating fields
            # Otherwise grid.point_data and cell_data will be empty
            self.loader.load_step_result(self.grid, self.current_step_idx)
            
            # Now populate fields (will see the loaded data)
            self._update_fields()

            # Initial display
            self._update_display(reset_cam=True)
            
        except Exception as e:
            self.plotter.add_text(f"Parse Error: {e}", position='upper_left', color='red')

    def _update_fields(self):
        """Populate field dropdown with available data fields."""
        if not self.grid:
            return
            
        self.field_combo.blockSignals(True)
        self.field_combo.clear()
        
        fields = []
        
        # Point data fields
        for k in self.grid.point_data.keys():
            fields.append(k)
            
        # Cell data fields (prefixed to distinguish)
        for k in self.grid.cell_data.keys():
            if k not in fields:
                fields.append(k)
        
        # Sort fields with priority order
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
        
        # Default selection
        if sorted_fields:
            self.field_combo.setCurrentIndex(0)
            
        self.field_combo.blockSignals(False)

    def on_slider_move(self, val):
        self.current_step_idx = val
        self._update_display(reset_cam=False)

    def on_field_changed(self, text):
        if not self.grid:
            return
        self._update_display(reset_cam=False)

    def _update_display(self, reset_cam=False):
        """Update 3D display with current step and field."""
        if not self.loader or not self.grid:
            return
        
        try:
            # Load step data
            self.loader.load_step_result(self.grid, self.current_step_idx)
            
            # Update labels
            if self.steps:
                t = self.steps[self.current_step_idx]
                self.time_label.setText(f"Time: {t:.4f}")
                self.step_label.setText(f"Step: {self.current_step_idx + 1}/{len(self.steps)}")
            
            # Warp by displacement if available
            display_mesh = self.grid
            if "displacement" in self.grid.point_data:
                with np.errstate(all='ignore'):
                    display_mesh = self.grid.warp_by_vector("displacement", factor=1.0)
            
            # Save camera
            cam = self.plotter.camera_position if not reset_cam else None
            
            self.plotter.clear()
            self._apply_plotter_theme()
            
            # Get current field
            scalar = self.field_combo.currentText()
            if not scalar:
                scalar = None
            
            # Get theme settings (flat dict now)
            cmap = self.theme.get("colormap", "turbo")
            legend_color = self.theme.get("legend_text_color", "#cccccc")
            title_size = self.theme.get("legend_title_size", 18)
            label_size = self.theme.get("legend_label_size", 14)
            edge_color = self.theme.get("edge_color", "#333333")
            
            # Scalar bar args
            sbar_args = {
                "title": scalar or "",
                "title_font_size": title_size,
                "label_font_size": label_size,
                "color": legend_color,
                "font_family": "arial"
            }
            
            # Add mesh
            if scalar and (scalar in display_mesh.point_data or scalar in display_mesh.cell_data):
                self.plotter.add_mesh(
                    display_mesh, 
                    scalars=scalar, 
                    cmap=cmap, 
                    show_edges=True,
                    edge_color=edge_color,
                    line_width=0.5,
                    scalar_bar_args=sbar_args
                )
            else:
                self.plotter.add_mesh(
                    display_mesh, 
                    color="lightblue", 
                    show_edges=True,
                    edge_color=edge_color
                )
                self.plotter.add_text("No scalar data for selected field", position='upper_left', color='white')
            
            if cam:
                self.plotter.camera_position = cam
            else:
                self.plotter.reset_camera()
                
        except Exception as e:
            print(f"Display Error: {e}")

    def cleanup(self):
        """Cleanup resources."""
        self._stop_loading_thread()
        try:
            self.plotter.close()
        except:
            pass

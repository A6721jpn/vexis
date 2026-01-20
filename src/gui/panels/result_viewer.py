import os
import yaml
import pyvista as pv
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                               QLabel, QSlider, QComboBox, QFrame, QTabWidget,
                               QSizePolicy)
from PySide6.QtCore import Qt, Signal, QThread
from pyvistaqt import QtInteractor
import numpy as np
import pandas as pd

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
        self.plotter_layout.setSpacing(0)
        
        self.plotter = QtInteractor(self.plotter_frame)
        self._apply_plotter_theme()
        self.plotter_layout.addWidget(self.plotter)
        
        # Loading overlay (centered in plotter_frame)
        self.loading_overlay = QLabel(self.plotter_frame)
        self.loading_overlay.setAlignment(Qt.AlignCenter)
        self.loading_overlay.setStyleSheet(
            "background-color: rgba(0,0,0,200); color: white; font-size: 18px; "
            "font-weight: bold; padding: 30px; border-radius: 10px;"
        )
        self.loading_overlay.hide()
        
        self.tab_widget.addTab(self.plotter_frame, "3D Contour")
        
        # --- Tab 2: Graph (Matplotlib Canvas) ---
        self.graph_frame = QFrame()
        self.graph_layout = QVBoxLayout(self.graph_frame)
        self.graph_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create matplotlib figure and canvas
        self.graph_figure = Figure(facecolor='#0B0F14')
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
        self.time_slider.valueChanged.connect(self.on_slider_move)
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
        
        # Set gradient background
        self.plotter.set_background(bg_bottom, top=bg_top)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_overlay_geometry()
    
    def _update_overlay_geometry(self):
        """Update loading overlay position and size."""
        if hasattr(self, 'loading_overlay') and self.loading_overlay.isVisible():
            # Center the overlay on the plotter_frame
            overlay_width = 250
            overlay_height = 80
            frame_rect = self.plotter_frame.rect()
            x = (frame_rect.width() - overlay_width) // 2
            y = (frame_rect.height() - overlay_height) // 2
            self.loading_overlay.setGeometry(x, y, overlay_width, overlay_height)
            self.loading_overlay.raise_()

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
        
        # Load graph from CSV
        self._update_graph(job_name)
        
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
        self._show_loading_overlay("Loading Result...")
        
        self._stop_loading_thread()

        self.load_thread = XpltLoaderThread(xplt_path)
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
            if csv_path and os.path.exists(csv_path):
                try:
                    df = pd.read_csv(csv_path)
                    if 'Stroke' in df.columns and 'Reaction_Force' in df.columns:
                        self._plot_graph(df, job_name)
                        return
                except Exception as e:
                    print(f"Error loading CSV: {e}")
        
        # Show no data message
        self._show_no_graph_message()
    
    def _plot_graph(self, df, title):
        """Plot Force-Stroke graph on the embedded canvas."""
        self.graph_figure.clear()
        ax = self.graph_figure.add_subplot(111)
        
        # Dark theme colors
        ax.set_facecolor('#0B0F14')
        ax.tick_params(colors='#6F8098')
        ax.spines['bottom'].set_color('#243244')
        ax.spines['top'].set_color('#243244')
        ax.spines['left'].set_color('#243244')
        ax.spines['right'].set_color('#243244')
        ax.xaxis.label.set_color('#EAF2FF')
        ax.yaxis.label.set_color('#EAF2FF')
        ax.title.set_color('#EAF2FF')
        
        # Plot data
        ax.plot(df['Stroke'], df['Reaction_Force'], 
                marker='o', color='#2EE7FF', markeredgecolor='white', 
                markersize=4, linewidth=2, label='KEYCAP Reaction')
        
        ax.set_title(title, fontsize=12, fontweight='bold')
        ax.set_xlabel('Stroke (mm)', fontsize=10)
        ax.set_ylabel('Reaction Force (N)', fontsize=10)
        ax.grid(True, linestyle='--', alpha=0.5, color='#243244')
        ax.legend(facecolor='#141E2A', edgecolor='#243244', labelcolor='#EAF2FF')
        
        self.graph_figure.tight_layout()
        self.graph_canvas.draw()
    
    def _show_no_graph_message(self):
        """Display 'no graph' message on the canvas."""
        self.graph_figure.clear()
        ax = self.graph_figure.add_subplot(111)
        ax.set_facecolor('#0B0F14')
        ax.text(0.5, 0.5, 'No graph available\n(Graph will be generated after analysis)',
                ha='center', va='center', fontsize=12, color='#6F8098',
                transform=ax.transAxes)
        ax.axis('off')
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
                # Convert Cell Data to Point Data for smooth gradient display
                # (Stress/Strain are computed at element level, need averaging at nodes)
                if scalar in display_mesh.cell_data and scalar not in display_mesh.point_data:
                    display_mesh = display_mesh.cell_data_to_point_data()
                
                # Surface without internal edges (fixes Hex20 diagonal line issue)
                self.plotter.add_mesh(
                    display_mesh, 
                    scalars=scalar, 
                    cmap=cmap, 
                    show_edges=False,
                    scalar_bar_args=sbar_args
                )
                
                # Overlay true cell edges (not triangulated face diagonals)
                edges = display_mesh.extract_all_edges()
                self.plotter.add_mesh(edges, color=edge_color, line_width=0.5)
            else:
                self.plotter.add_mesh(
                    display_mesh, 
                    color="lightblue", 
                    show_edges=False
                )
                
                # Overlay true cell edges
                edges = display_mesh.extract_all_edges()
                self.plotter.add_mesh(edges, color=edge_color, line_width=0.5)
                
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

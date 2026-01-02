import os
import glob
import re
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QComboBox, QTabWidget, QScrollArea, QSlider, QCheckBox)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

# Lazy import
PYVISTA_AVAILABLE = False
pv = None
QtInteractor = None

def _ensure_pyvista():
    global PYVISTA_AVAILABLE, pv, QtInteractor
    if pv is None:
        try:
            import pyvista as _pv
            from pyvistaqt import QtInteractor as _QtInteractor
            pv = _pv
            QtInteractor = _QtInteractor
            PYVISTA_AVAILABLE = True
        except ImportError:
            PYVISTA_AVAILABLE = False
    return PYVISTA_AVAILABLE

class ResultViewer(QWidget):
    def __init__(self):
        super().__init__()
        self.mesh = None
        self.plotter = None
        self._plotter_initialized = False
        self.vtk_files = []
        self._mesh_cache = {}
        self.current_step = 0
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Tab widget to switch between Graph and 3D views
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)
        
        # Tab 1: Graph (PNG)
        self.graph_widget = QWidget()
        graph_layout = QVBoxLayout(self.graph_widget)
        
        self.graph_scroll = QScrollArea()
        self.graph_scroll.setWidgetResizable(True)
        self.graph_label = QLabel("No graph available")
        self.graph_label.setAlignment(Qt.AlignCenter)
        self.graph_label.setStyleSheet("background-color: white;")
        self.graph_scroll.setWidget(self.graph_label)
        graph_layout.addWidget(self.graph_scroll)
        
        self.tab_widget.addTab(self.graph_widget, "📊 Graph")
        
        # Tab 2: 3D View (xplt)
        self.view3d_widget = QWidget()
        self.view3d_layout = QVBoxLayout(self.view3d_widget)
        
        # Controls Layer
        ctrl_layout = QHBoxLayout()
        
        ctrl_layout.addWidget(QLabel("Field:"))
        self.field_combo = QComboBox()
        self.field_combo.currentTextChanged.connect(self.on_field_changed)
        ctrl_layout.addWidget(self.field_combo)
        
        # Wireframe toggle
        self.wireframe_check = QCheckBox("Show Edges")
        self.wireframe_check.setChecked(True)
        self.wireframe_check.stateChanged.connect(self.on_wireframe_changed)
        ctrl_layout.addWidget(self.wireframe_check)
        
        ctrl_layout.addStretch()
        self.view3d_layout.addLayout(ctrl_layout)
        
        # PyVista Plotter
        self.placeholder_3d = QLabel("Select a completed job to view 3D results")
        self.placeholder_3d.setAlignment(Qt.AlignCenter)
        self.placeholder_3d.setStyleSheet("background-color: #3d3d3d; color: #888;")
        self.view3d_layout.addWidget(self.placeholder_3d)
        
        # Timeline Slider
        self.slider_layout = QHBoxLayout()
        self.time_label = QLabel("Step: 0 / 0")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self.set_step)
        
        self.slider_layout.addWidget(QLabel("Time:"))
        self.slider_layout.addWidget(self.slider)
        self.slider_layout.addWidget(self.time_label)
        
        self.view3d_layout.addLayout(self.slider_layout)
        
        self.tab_widget.addTab(self.view3d_widget, "🔷 3D Result")

    def _init_plotter(self):
        if self._plotter_initialized:
            return
        if not _ensure_pyvista():
            self.placeholder_3d.setText("pyvistaqt not installed")
            return
            
        self._plotter_initialized = True
        self.placeholder_3d.hide()
        self.plotter = QtInteractor(self.view3d_widget)
        self.view3d_layout.insertWidget(1, self.plotter) # Insert between controls and slider
        self.plotter.set_background("dimgray", top="lightgray")

    def load_result(self, job_name, result_dir, temp_dir):
        """Load both graph and 3D result for a job."""
        self._mesh_cache.clear() # Clear cache for new job
        self._temp_dir = temp_dir
        self._job_name = job_name
        
        # Load Graph PNG
        graph_path = os.path.join(result_dir, f"{job_name}_graph.png")
        if os.path.exists(graph_path):
            pixmap = QPixmap(graph_path)
            self.graph_label.setPixmap(pixmap.scaled(
                800, 600, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.graph_label.setText(f"Graph not found:\n{graph_path}")
        
        # Load 3D: Search for all VTK results (time series)
        pattern = os.path.join(temp_dir, f"{job_name}*.vtk")
        candidates = glob.glob(pattern)
        
        self.vtk_files = []
        if candidates:
            # Sort strategically: try to extract numbers from filenames
            def sort_key(path):
                base = os.path.basename(path)
                nums = re.findall(r'\d+', base)
                if nums:
                    return int(nums[-1])
                return 0 # Fallback
            candidates.sort(key=os.path.getmtime)
            self.vtk_files = candidates

        if self.vtk_files:
            self.slider.setEnabled(True)
            self.slider.setRange(0, len(self.vtk_files) - 1)
            
            # Auto-set to last step
            last_step = len(self.vtk_files) - 1
            self.slider.setValue(last_step)
            self.set_step(last_step)
            
        else:
            self.slider.setEnabled(False)
            self.time_label.setText("Step: 0 / 0")
            self._init_plotter()
            if self.plotter:
                self.plotter.clear()
                self.plotter.add_text(
                    "3D result visualization:\nNo .vtk files found in temp/.\n"
                    "Ensure FEBio output is set to VTK in template.", 
                    position='upper_left', font_size=10)

    def set_step(self, step_index):
        if not self.vtk_files or step_index < 0 or step_index >= len(self.vtk_files):
            return
            
        self.current_step = step_index
        self.time_label.setText(f"Step: {step_index + 1} / {len(self.vtk_files)}")
        
        vtk_path = self.vtk_files[step_index]
        self._load_mesh_file(vtk_path, is_result=True, reset_cam=(step_index == 0))

    def _load_mesh_file(self, file_path, is_result=True, reset_cam=True):
        """Load a mesh file (VTK, etc). Uses caching."""
        self._init_plotter()
        if not self.plotter:
            return
            
        try:
            # Check cache first
            if file_path in self._mesh_cache:
                self.mesh = self._mesh_cache[file_path]
            else:
                self.mesh = pv.read(file_path)
                self._mesh_cache[file_path] = self.mesh
                
            self._display_mesh(is_result=is_result, reset_cam=reset_cam)
        except Exception as e:
            print(f"Mesh load error: {e}")
            self.plotter.clear()
            self.plotter.add_text(f"Error: {str(e)}", position='upper_left')

    def _display_mesh(self, is_result=True, reset_cam=True):
        """Display the loaded mesh with field selection."""
        if not self.mesh or not self.plotter:
            return
            
        # Store current camera position if not resetting
        camera = None
        if not reset_cam:
            camera = self.plotter.camera_position

        self.plotter.clear()
        
        # Update field combo only if needed (to avoid flickering logic, or just refresh)
        current_field = self.field_combo.currentText()
        
        self.field_combo.blockSignals(True)
        self.field_combo.clear()
        point_fields = list(self.mesh.point_data.keys())
        cell_fields = list(self.mesh.cell_data.keys())
        fields = point_fields + cell_fields
        self.field_combo.addItems(fields)
        
        # Restore selection if possible
        if current_field and current_field in fields:
            self.field_combo.setCurrentText(current_field)
        self.field_combo.blockSignals(False)
        
        # Warp mesh if displacement data exists
        display_mesh = self.mesh
        if "displacement" in self.mesh.point_data:
            try:
                # Apply deformation (scale factor 1.0)
                display_mesh = self.mesh.warp_by_vector("displacement")
            except Exception as e:
                print(f"Warp error: {e}")
                # Fallback to original mesh
                display_mesh = self.mesh

        show_edges = self.wireframe_check.isChecked()
        
        # Add main mesh (surface/contour) without edges (to avoid triangulation artifacts)
        if current_field and current_field in fields:
            self.plotter.add_mesh(display_mesh, scalars=current_field, cmap="jet", show_edges=False)
            self.plotter.add_scalar_bar(title=current_field)
        elif fields:
            first_field = fields[0]
            self.field_combo.setCurrentText(first_field)
            self.plotter.add_mesh(display_mesh, scalars=first_field, cmap="jet", show_edges=False)
            self.plotter.add_scalar_bar(title=first_field)
        else:
            self.plotter.add_mesh(display_mesh, color="lightblue", show_edges=False)
            if is_result:
                self.plotter.add_text("Mesh loaded (no scalar data)", position='upper_left', font_size=10)
            else:
                self.plotter.add_text("Mesh preview (analysis mesh)", position='upper_left', font_size=10)
        
        # Explicitly extract and show edges to preserve Hex structure
        # (show_edges=True often shows triangulation on non-planar quads)
        if show_edges:
            # Attempt to use linear_copy to avoid showing diagonals of quadratic faces
            edge_mesh = display_mesh
            if hasattr(display_mesh, 'linear_copy'):
                try:
                    edge_mesh = display_mesh.linear_copy()
                except Exception:
                    pass
            
            edges = edge_mesh.extract_all_edges()
            self.plotter.add_mesh(edges, color="black", line_width=1)
        
        if reset_cam:
            self.plotter.reset_camera()
        elif camera:
            self.plotter.camera_position = camera

    def on_field_changed(self, field_name):
        if not self.mesh or not self.plotter:
            return
        
        # Just refresh display, keeping camera
        self._display_mesh(is_result=True, reset_cam=False)

    def on_wireframe_changed(self, _):
        if not self.mesh or not self.plotter:
            return
        # Refresh display
        self._display_mesh(is_result=True, reset_cam=False)

    def clear(self):
        if self.plotter:
            self.plotter.clear()
        self.field_combo.clear()
        self.vtk_files = []
        self._mesh_cache.clear()
        self.mesh = None
        self.slider.setEnabled(False)
        self.time_label.setText("Step: 0 / 0")
        self.graph_label.setText("No graph available")

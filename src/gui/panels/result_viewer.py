import os
import glob
import re
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QComboBox, QTabWidget, QScrollArea, QSlider, QCheckBox,
                               QApplication)
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
        self._mesh_cache = {}      # Raw VTK file cache
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
        self.graph_label.setStyleSheet("background-color: #0B0F14; color: #6F8098")
        self.graph_label.setScaledContents(True) # Allow scaling
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
        self.field_combo.setMinimumWidth(150)  # Ensure enough space for field names
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
        self.placeholder_3d.setStyleSheet("background-color: #0B0F14; color: #6F8098;")
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
        
        # Loading Overlay (hidden by default)
        self.loading_overlay = QLabel("⏳ Loading Results...")
        self.loading_overlay.setAlignment(Qt.AlignCenter)
        self.loading_overlay.setStyleSheet("""
            background-color: rgba(11, 15, 20, 0.9);
            color: #2EE7FF;
            font-size: 18px;
            font-weight: bold;
            border-radius: 10px;
        """)
        self.loading_overlay.hide()
        self.view3d_layout.addWidget(self.loading_overlay)
        
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
        self.plotter.set_background("#0B0F14", top="#141E2A")

    def load_result(self, job_name, result_dir, temp_dir):
        """Load both graph and 3D result for a job."""
        # Clear cache for new job
        self._mesh_cache.clear()
        self._temp_dir = temp_dir
        self._job_name = job_name
        
        # Load Graph PNG
        graph_path = os.path.join(result_dir, f"{job_name}_graph.png")
        if os.path.exists(graph_path):
            pixmap = QPixmap(graph_path)
            # Scaling is handled by setScaledContents(True) combined with widget layout
            # But setScaledContents needs the pixmap to be set.
            # To ensure it fits nicely without initial pixelation, we can set it directly.
            self.graph_label.setPixmap(pixmap)
            # Note: For QScrollArea with resizable widget to scale image properly,
            # usually requires subclassing/events, but setScaledContents does a basic job.
            self.graph_label.adjustSize()
        else:
            self.graph_label.setText(f"Graph not found:\n{graph_path}")
        
        # Load 3D: Search for all VTK results (time series)
        # Use more specific pattern: job_name.X.vtk or job_name.vtk (exact match, not prefix)
        # This prevents case_1 from matching case_10, case_11, etc.
        self.vtk_files = []
        
        # Show loading overlay early to prevent perceived freeze
        self.loading_overlay.setText("⏳ Scanning result files...")
        self.loading_overlay.show()
        QApplication.processEvents()
        
        # Find files with exact job name match (fast filename-based filtering)
        all_vtk = glob.glob(os.path.join(temp_dir, "*.vtk"))
        candidates = []
        for vtk_path in all_vtk:
            base = os.path.basename(vtk_path)
            # Match: job_name.vtk or job_name.N.vtk (where N is step number)
            if base == f"{job_name}.vtk" or base.startswith(f"{job_name}.") and base.endswith(".vtk"):
                # But exclude files like job_name_tmp.vtk or job_nameX.vtk
                name_without_ext = base[:-4]  # Remove .vtk
                parts = name_without_ext.split('.')
                if parts[0] == job_name:
                    candidates.append(vtk_path)
        
        if candidates:
            # Sort by modification time first
            candidates.sort(key=os.path.getmtime)
            
            # Combined filter + pre-cache in single pass (read each file only once)
            self._init_plotter()
            
            for i, vtk_path in enumerate(candidates):
                self.loading_overlay.setText(f"⏳ Loading step {i+1}/{len(candidates)}...")
                QApplication.processEvents()
                
                try:
                    mesh = pv.read(vtk_path)
                    
                    # Filter: only include files with displacement (FEBio output)
                    if "displacement" not in mesh.point_data:
                        continue
                    
                    # Cache raw mesh only (no warp/edge pre-computation for speed)
                    self._mesh_cache[vtk_path] = mesh
                    
                    # Add to valid file list
                    self.vtk_files.append(vtk_path)
                    
                except BaseException as e:
                    # Catch all errors including VTK/C++ level errors
                    print(f"Load error for {vtk_path}: {e}")
            
            self.loading_overlay.hide()
            QApplication.processEvents()
        
        # Setup slider and display after loading
        if self.vtk_files:
            self.slider.setEnabled(True)
            self.slider.setRange(0, len(self.vtk_files) - 1)
            
            # Auto-set to last step
            last_step = len(self.vtk_files) - 1
            self.slider.setValue(last_step)
            self.set_step(last_step, force_reset=True)
            
        else:
            self.loading_overlay.hide()
            self.slider.setEnabled(False)
            self.time_label.setText("Step: 0 / 0")
            self._init_plotter()
            if self.plotter:
                self.plotter.clear()
                self.plotter.add_text(
                    "3D result visualization:\nNo .vtk files found in temp/.\n"
                    "Ensure FEBio output is set to VTK in template.", 
                    position='upper_left', font_size=10)

    def _precache_all_steps(self):
        """Pre-cache all VTK steps (warp + edges) with loading indicator."""
        if not self.vtk_files:
            return
            
        self._init_plotter()
        
        # Show loading overlay
        self.loading_overlay.setText(f"⏳ Loading {len(self.vtk_files)} time steps...")
        self.loading_overlay.show()
        QApplication.processEvents()
        
        total = len(self.vtk_files)
        for i, vtk_path in enumerate(self.vtk_files):
            # Update loading text with progress
            self.loading_overlay.setText(f"⏳ Loading step {i+1}/{total}...")
            QApplication.processEvents()
            
            try:
                # Read and cache raw mesh
                if vtk_path not in self._mesh_cache:
                    self._mesh_cache[vtk_path] = pv.read(vtk_path)
                
                raw_mesh = self._mesh_cache[vtk_path]
                
                # Compute and cache warped mesh
                if vtk_path not in self._warped_cache:
                    if "displacement" in raw_mesh.point_data:
                        try:
                            warped = raw_mesh.warp_by_vector("displacement")
                        except Exception:
                            warped = raw_mesh
                    else:
                        warped = raw_mesh
                    self._warped_cache[vtk_path] = warped
                
                # Compute and cache edges
                if vtk_path not in self._edge_cache:
                    warped = self._warped_cache[vtk_path]
                    edge_mesh = warped
                    if hasattr(warped, 'linear_copy'):
                        try:
                            edge_mesh = warped.linear_copy()
                        except Exception:
                            pass
                    edges = edge_mesh.extract_all_edges()
                    self._edge_cache[vtk_path] = edges
                    
            except Exception as e:
                print(f"Pre-cache error for {vtk_path}: {e}")
        
        # Hide loading overlay
        self.loading_overlay.hide()
        QApplication.processEvents()

    def set_step(self, step_index, force_reset=False):
        if not self.vtk_files or step_index < 0 or step_index >= len(self.vtk_files):
            return
            
        self.current_step = step_index
        self.time_label.setText(f"Step: {step_index + 1} / {len(self.vtk_files)}")
        
        vtk_path = self.vtk_files[step_index]
        # Only reset camera on explicit force_reset (initial load), not every time step 0 is shown
        self._load_mesh_file(vtk_path, is_result=True, reset_cam=force_reset)

    def _load_mesh_file(self, file_path, is_result=True, reset_cam=True):
        """Load a mesh file (VTK, etc). Uses caching for raw mesh."""
        self._init_plotter()
        if not self.plotter:
            return
            
        try:
            # Check raw cache
            if file_path in self._mesh_cache:
                self.mesh = self._mesh_cache[file_path]
            else:
                self.mesh = pv.read(file_path)
                self._mesh_cache[file_path] = self.mesh
            
            # Compute warped mesh on-demand (not cached for memory efficiency)
            if "displacement" in self.mesh.point_data:
                try:
                    self._current_warped = self.mesh.warp_by_vector("displacement")
                except Exception as e:
                    print(f"Warp error: {e}")
                    self._current_warped = self.mesh
            else:
                self._current_warped = self.mesh
                
            self._display_mesh(is_result=is_result, reset_cam=reset_cam)
        except Exception as e:
            print(f"Mesh load error: {e}")
            try:
                if self.plotter:
                    self.plotter.clear()
                    self.plotter.add_text(f"Error: {str(e)}", position='upper_left')
            except Exception:
                pass  # Plotter may be closed during shutdown

    def _display_mesh(self, is_result=True, reset_cam=True):
        """Display the loaded mesh with field selection."""
        if not self.mesh or not self.plotter:
            return
            
        # Store current camera position if not resetting
        camera = None
        try:
            if not reset_cam:
                camera = self.plotter.camera_position
            self.plotter.clear()
        except Exception:
            return  # Plotter may be closed during shutdown
        
        # Update field combo only if needed (to avoid flickering logic, or just refresh)
        current_field = self.field_combo.currentText()
        
        self.field_combo.blockSignals(True)
        self.field_combo.clear()
        point_fields = list(self.mesh.point_data.keys())
        cell_fields = list(self.mesh.cell_data.keys())
        
        # Filter out unwanted fields
        hidden_fields = {'part_id', 'relative_volume', 'gmsh:dim_tags'}
        fields = [f for f in point_fields + cell_fields if f not in hidden_fields]
        
        self.field_combo.addItems(fields)
        
        # Restore selection if possible
        if current_field and current_field in fields:
            self.field_combo.setCurrentText(current_field)
        self.field_combo.blockSignals(False)
        
        # Use cached warped mesh instead of computing every time
        display_mesh = getattr(self, '_current_warped', self.mesh)
        if display_mesh is None:
            display_mesh = self.mesh

        show_edges = self.wireframe_check.isChecked()
        
        # Add main mesh (surface/contour) without edges (to avoid triangulation artifacts)
        # Add main mesh (surface/contour) without edges (to avoid triangulation artifacts)
        # scalar_bar_args controls the legend color (white text for dark theme)
        sb_args = dict(title_font_size=20, label_font_size=16, color="white", font_family="arial")
        
        if current_field and current_field in fields:
            self.plotter.add_mesh(display_mesh, scalars=current_field, cmap="jet", show_edges=False,
                                  scalar_bar_args={**sb_args, "title": current_field})
        elif fields:
            first_field = fields[0]
            self.field_combo.setCurrentText(first_field)
            self.plotter.add_mesh(display_mesh, scalars=first_field, cmap="jet", show_edges=False,
                                  scalar_bar_args={**sb_args, "title": first_field})
        else:
            self.plotter.add_mesh(display_mesh, color="lightblue", show_edges=False)
            if is_result:
                self.plotter.add_text("Mesh loaded (no scalar data)", position='upper_left', font_size=10, color='white')
            else:
                self.plotter.add_text("Mesh preview (analysis mesh)", position='upper_left', font_size=10, color='white')
        
        # Show edges using PyVista's built-in parameter (faster than manual extraction)
        # Note: This shows triangulation edges, but is much faster
        if show_edges and display_mesh is not None:
            # Add edge overlay
            self.plotter.add_mesh(display_mesh.extract_surface(), style='wireframe', 
                                  color='black', line_width=0.5, opacity=0.3)
        
        if reset_cam:
            self.plotter.reset_camera()
            self.plotter.camera.zoom(0.8) # Zoom out to fit model comfortably
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
        self._warped_cache.clear()
        self._edge_cache.clear()
        self.mesh = None
        self._current_warped = None
        self.slider.setEnabled(False)
        self.time_label.setText("Step: 0 / 0")
        self.graph_label.setText("No graph available")

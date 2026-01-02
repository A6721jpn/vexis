import os
import tempfile
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

# Lazy import to avoid OpenGL context conflicts
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

def _step_to_temp_mesh(step_path):
    """Convert STEP file to temporary VTK mesh for visualization using gmsh."""
    try:
        import gmsh
        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 0)  # Suppress output
        gmsh.model.add("preview")
        gmsh.model.occ.importShapes(step_path)
        gmsh.model.occ.synchronize()
        
        # Fine mesh for smooth preview
        gmsh.option.setNumber("Mesh.MeshSizeMin", 0.1)
        gmsh.option.setNumber("Mesh.MeshSizeMax", 0.3)
        gmsh.option.setNumber("Mesh.Algorithm", 6)  # Frontal-Delaunay for better quality
        gmsh.model.mesh.generate(2)  # Surface mesh only for speed
        
        # Save to temp file
        temp_file = tempfile.NamedTemporaryFile(suffix=".vtk", delete=False)
        temp_path = temp_file.name
        temp_file.close()
        gmsh.write(temp_path)
        gmsh.finalize()
        return temp_path
    except Exception as e:
        print(f"STEP preview generation error: {e}")
        try:
            gmsh.finalize()
        except:
            pass
        return None

class MeshPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.plotter = None
        self._initialized = False
        self._temp_file = None
        self.layout = QVBoxLayout(self)
        
        self.placeholder = QLabel("Geometry Preview\n(Select a job)")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setStyleSheet("background-color: #2d2d2d; color: #888;")
        self.layout.addWidget(self.placeholder)

    def _init_plotter(self):
        if self._initialized:
            return
        if not _ensure_pyvista():
            self.placeholder.setText("pyvistaqt not installed")
            return
        
        self._initialized = True
        self.placeholder.hide()
        self.plotter = QtInteractor(self)
        self.layout.addWidget(self.plotter)
        # Gray gradient background
        self.plotter.set_background("dimgray", top="lightgray")

    def load_mesh(self, vtk_path):
        """Load mesh file for preview."""
        self._cleanup_temp()
        
        if not os.path.exists(vtk_path):
            self.placeholder.setText("Mesh not available")
            self.placeholder.show()
            if self.plotter:
                self.plotter.hide()
            return
            
        self._init_plotter()
        if not self.plotter:
            return
        
        self.placeholder.hide()
        self.plotter.show()

        try:
            mesh = pv.read(vtk_path)
            self.plotter.clear()
            self.plotter.add_mesh(mesh, show_edges=True, color="lightblue")
            self.plotter.reset_camera()
        except Exception as e:
            print(f"Mesh Preview Error: {e}")

    def load_step(self, step_path):
        """Load STEP file for geometry preview (converts to temp mesh)."""
        self._cleanup_temp()
        
        if not os.path.exists(step_path):
            self.placeholder.setText("STEP file not found")
            self.placeholder.show()
            if self.plotter:
                self.plotter.hide()
            return
        
        # Show loading message
        self.placeholder.setText("Loading geometry...")
        self.placeholder.show()
        if self.plotter:
            self.plotter.hide()
        
        # Convert STEP to temp mesh
        temp_path = _step_to_temp_mesh(step_path)
        if not temp_path:
            self.placeholder.setText("Failed to load STEP geometry")
            return
        
        self._temp_file = temp_path
        
        self._init_plotter()
        if not self.plotter:
            return
        
        self.placeholder.hide()
        self.plotter.show()

        try:
            mesh = pv.read(temp_path)
            self.plotter.clear()
            
            # Show surface without mesh lines
            self.plotter.add_mesh(mesh, show_edges=False, color="orange", opacity=1.0)
            
            # Extract and show only feature edges (outer boundary and sharp edges)
            edges = mesh.extract_feature_edges(
                boundary_edges=True, 
                feature_edges=True, 
                manifold_edges=False,
                non_manifold_edges=False,
                feature_angle=30
            )
            self.plotter.add_mesh(edges, color="black", line_width=2, 
                                  render_points_as_spheres=False, point_size=0)
            
            self.plotter.add_text("STEP Geometry", position='upper_left', font_size=10, color='black')
            self.plotter.reset_camera()
        except Exception as e:
            print(f"STEP Preview Error: {e}")
            self.placeholder.setText(f"Preview error: {str(e)}")
            self.placeholder.show()

    def _cleanup_temp(self):
        if self._temp_file and os.path.exists(self._temp_file):
            try:
                os.remove(self._temp_file)
            except:
                pass
            self._temp_file = None

    def clear(self):
        self._cleanup_temp()
        if self.plotter:
            self.plotter.clear()

    def closeEvent(self, event):
        self._cleanup_temp()
        super().closeEvent(event)

import os
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
try:
    from pyvistaqt import QtInteractor
    import pyvista as pv
    PYVISTA_AVAILABLE = True
except ImportError:
    PYVISTA_AVAILABLE = False

class MeshPreview(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        
        if PYVISTA_AVAILABLE:
            self.plotter = QtInteractor(self)
            layout.addWidget(self.plotter)
            self.plotter.set_background("black")
        else:
            self.label = QLabel("pyvistaqt not installed. Cannot preview mesh.")
            self.label.setAlignment(Qt.AlignCenter)
            layout.addWidget(self.label)
            self.plotter = None

    def load_mesh(self, vtk_path):
        if not PYVISTA_AVAILABLE or not self.plotter:
            return
            
        if not os.path.exists(vtk_path):
            self.plotter.clear()
            self.plotter.add_text("Mesh file not found", position='upper_left', font_size=10)
            return

        try:
            mesh = pv.read(vtk_path)
            self.plotter.clear()
            self.plotter.add_mesh(mesh, show_edges=True, color="lightblue")
            self.plotter.reset_camera()
        except Exception as e:
            print(f"Mesh Preview Error: {e}")

    def clear(self):
        if self.plotter:
            self.plotter.clear()

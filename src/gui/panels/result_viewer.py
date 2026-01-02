import os
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox
from PySide6.QtCore import Qt

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
        self._initialized = False
        self._setup_ui()
        
    def _setup_ui(self):
        self.layout = QVBoxLayout(self)
        
        ctrl_layout = QHBoxLayout()
        ctrl_layout.addWidget(QLabel("Field:"))
        self.field_combo = QComboBox()
        self.field_combo.currentTextChanged.connect(self.on_field_changed)
        ctrl_layout.addWidget(self.field_combo)
        ctrl_layout.addStretch()
        self.layout.addLayout(ctrl_layout)
        
        self.placeholder = QLabel("Result Viewer\n(Select a completed job)")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setStyleSheet("background-color: #3d3d3d; color: #888;")
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
        self.plotter.set_background("dimgray")

    def load_result(self, base_path_no_ext):
        self._init_plotter()
        if not self.plotter:
            return
            
        possible_exts = [".vtk", ".pos", ".xdmf"]
        found_path = None
        
        for ext in possible_exts:
            p = base_path_no_ext + ext
            if os.path.exists(p):
                found_path = p
                break
        
        if not found_path:
            if os.path.exists(base_path_no_ext + ".vtk"):
                found_path = base_path_no_ext + ".vtk"

        if not found_path:
            self.plotter.clear()
            self.plotter.add_text("No result file found", position='upper_left')
            return

        try:
            self.mesh = pv.read(found_path)
            self.plotter.clear()
            
            self.field_combo.clear()
            point_fields = list(self.mesh.point_data.keys())
            cell_fields = list(self.mesh.cell_data.keys())
            fields = point_fields + cell_fields
            self.field_combo.addItems(fields)
            
            if fields:
                self.on_field_changed(fields[0])
            else:
                self.plotter.add_mesh(self.mesh, color="gray", show_edges=True)
                self.plotter.add_text("No results in file (Mesh only)", position='upper_left', font_size=10)
            
            self.plotter.add_scalar_bar()
            self.plotter.reset_camera()
        except Exception as e:
            print(f"Result Viewer Error loading {found_path}: {e}")
            self.plotter.add_text(f"Error: {str(e)}", position='upper_left')

    def on_field_changed(self, field_name):
        if not self.mesh or not self.plotter:
            return
        
        self.plotter.clear()
        self.plotter.add_mesh(self.mesh, scalars=field_name, cmap="jet")
        self.plotter.reset_camera()

    def clear(self):
        if self.plotter:
            self.plotter.clear()
        self.field_combo.clear()
        self.mesh = None

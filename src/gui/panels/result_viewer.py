import os
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox
from PySide6.QtCore import Qt

try:
    from pyvistaqt import QtInteractor
    import pyvista as pv
    PYVISTA_AVAILABLE = True
except ImportError:
    PYVISTA_AVAILABLE = False

class ResultViewer(QWidget):
    def __init__(self):
        super().__init__()
        self.mesh = None
        self._setup_ui()
        
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Toolbar for selection
        ctrl_layout = QHBoxLayout()
        ctrl_layout.addWidget(QLabel("Field:"))
        self.field_combo = QComboBox()
        self.field_combo.currentTextChanged.connect(self.on_field_changed)
        ctrl_layout.addWidget(self.field_combo)
        ctrl_layout.addStretch()
        layout.addLayout(ctrl_layout)
        
        if PYVISTA_AVAILABLE:
            self.plotter = QtInteractor(self)
            layout.addWidget(self.plotter)
            self.plotter.set_background("dimgray")
        else:
            self.label = QLabel("pyvistaqt not installed.")
            layout.addWidget(self.label)
            self.plotter = None

    def load_result(self, base_path_no_ext):
        if not PYVISTA_AVAILABLE or not self.plotter:
            return
            
        # Try to find a result file. Priority: .vtk (with results), .pos, .xdmf
        # If none found, use the mesh .vtk as fallback
        possible_exts = [".vtk", ".pos", ".xdmf"]
        found_path = None
        
        # Check results/ first
        for ext in possible_exts:
            p = base_path_no_ext + ext
            if os.path.exists(p):
                found_path = p
                break
        
        if not found_path:
            # Fallback to temp mesh if provided
            if os.path.exists(base_path_no_ext + ".vtk"):
                found_path = base_path_no_ext + ".vtk"

        if not found_path:
            self.plotter.clear()
            self.plotter.add_text("No result file found", position='upper_left')
            return

        try:
            self.mesh = pv.read(found_path)
            self.plotter.clear()
            
            # Update field combo
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
            self.plotter.add_text(f"Error loading results: {str(e)}", position='upper_left')

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

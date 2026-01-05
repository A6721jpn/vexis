
import pyvista as pv
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                               QLabel, QSlider, QComboBox, QMessageBox, QFrame,
                               QProgressBar)
from PySide6.QtCore import Qt, Signal, QThread
from pyvistaqt import QtInteractor
import numpy as np

# Import WaffleironLoader
from src.utils.xplt_loader import WaffleironLoader

class XpltLoaderThread(QThread):
    finished = Signal(object, str) # loader, error_message
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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_job = None
        self.loader = None # WaffleironLoader instance
        self.grid = None   # PyVista mesh (UnstructuredGrid)
        self.steps = []
        self.current_step_idx = 0
        
        self.load_thread = None

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Top Control Bar
        ctrl_layout = QHBoxLayout()
        
        # Job Name Label
        self.job_label = QLabel("No Job Selected")
        self.job_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        ctrl_layout.addWidget(self.job_label)
        
        ctrl_layout.addStretch()

        # Field Selector
        ctrl_layout.addWidget(QLabel("Field:"))
        self.field_combo = QComboBox()
        self.field_combo.setMinimumWidth(150)
        self.field_combo.currentTextChanged.connect(self.on_field_changed)
        ctrl_layout.addWidget(self.field_combo)

        layout.addLayout(ctrl_layout)

        # PyVista Plotter
        self.plotter_frame = QFrame()
        self.plotter_layout = QVBoxLayout(self.plotter_frame)
        self.plotter_layout.setContentsMargins(0,0,0,0)
        
        self.plotter = QtInteractor(self.plotter_frame)
        self.plotter_layout.addWidget(self.plotter)
        
        layout.addWidget(self.plotter_frame)

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
        self.step_label.setFixedWidth(80)
        self.step_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        time_layout.addWidget(self.step_label)

        layout.addLayout(time_layout)

        # Loading Overlay (Simple Label centered)
        self.loading_overlay = QLabel("Loading...", self.plotter)
        self.loading_overlay.setAlignment(Qt.AlignCenter)
        self.loading_overlay.setStyleSheet("background-color: rgba(0,0,0,150); color: white; font-size: 16px;")
        self.loading_overlay.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.loading_overlay.resize(self.plotter.size())

    def load_result(self, job_name, result_dir, temp_dir):
        """Called by MainWindow when a job is selected."""
        # self.current_job = job_item # No longer storing object, just display name
        self.job_label.setText(job_name)
        
        # Clear previous
        self.plotter.clear()
        self.loader = None
        self.grid = None
        self.steps = []
        self.field_combo.clear()
        self.time_slider.setEnabled(False)
        self.time_label.setText("Time: 0.00")
        self.step_label.setText("Step: 0/0")
        
        import os
        base = job_name
        
        # Try finding xplt
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
            self.plotter.add_text("No .xplt file found", position='upper_left')
            return

        # Start loading thread
        self.loading_overlay.setText("Loading Result...")
        self.loading_overlay.show()
        
        # Stop previous thread if any
        if self._stop_loading_thread():
             pass

        self.load_thread = XpltLoaderThread(xplt_path)
        self.load_thread.finished.connect(self._on_load_finished)
        self.load_thread.start()

    def _stop_loading_thread(self):
        if self.load_thread and self.load_thread.isRunning():
            self.load_thread.terminate()
            self.load_thread.wait()
            return True
        return False

    def _on_load_finished(self, loader, error_msg):
        self.loading_overlay.hide()
        if error_msg:
            self.plotter.add_text(f"Error: {error_msg}", position='upper_left')
            return
            
        if not loader:
            return

        self.loader = loader
        
        # Get Mesh
        try:
            self.grid = self.loader.get_mesh()
            self.steps = self.loader.get_time_steps()
            
            # Setup slider
            if self.steps:
                self.time_slider.blockSignals(True)
                self.time_slider.setRange(0, len(self.steps) - 1)
                self.time_slider.setValue(len(self.steps) - 1) # Last step
                self.time_slider.setEnabled(True)
                self.time_slider.blockSignals(False)
                self.current_step_idx = len(self.steps) - 1
            
            # Populate fields
            self._update_fields()

            # Initial display
            self._update_display(reset_cam=True)
            
        except Exception as e:
            self.plotter.add_text(f"Parse Error: {e}", position='upper_left')

    def _update_fields(self):
        if not self.grid: return
        self.field_combo.blockSignals(True)
        self.field_combo.clear()
        
        fields = []
        # Point data
        for k in self.grid.point_data.keys():
            fields.append(k)
        # Cell data
        for k in self.grid.cell_data.keys():
            fields.append(k)
            
        # Prioritize displacement or stress
        self.field_combo.addItems(fields)
        if "displacement" in fields:
            self.field_combo.setCurrentText("displacement")
            
        self.field_combo.blockSignals(False)

    def on_slider_move(self, val):
        self.current_step_idx = val
        self._update_display(reset_cam=False)

    def on_field_changed(self, text):
        if not self.grid: return
        self._update_display(reset_cam=False)

    def _update_display(self, reset_cam=False):
        if not self.loader or not self.grid: return
        
        # Load step data (fast in-memory)
        try:
            self.loader.load_step_result(self.grid, self.current_step_idx)
            
            # Update time label
            if self.steps:
                t = self.steps[self.current_step_idx]
                self.time_label.setText(f"Time: {t:.4f}")
                self.step_label.setText(f"Step: {self.current_step_idx}/{len(self.steps)-1}")
            
            # Warp by displacement if available
            display_mesh = self.grid
            if "displacement" in self.grid.point_data:
                # Warp
                warn_old = np.seterr(all='ignore') # PyVista/VTK sometimes warns on warp
                display_mesh = self.grid.warp_by_vector("displacement", factor=1.0)
                np.seterr(**warn_old)
            
            # Add to plotter
            # Save camera
            cam = self.plotter.camera_position if not reset_cam else None
            
            self.plotter.clear()
            
            scalar = self.field_combo.currentText()
            if not scalar: scalar = None
            
            self.plotter.add_mesh(display_mesh, show_edges=True, scalars=scalar, cmap="turbo")
            
            if cam:
                self.plotter.camera_position = cam
            else:
                self.plotter.reset_camera()
                
        except Exception as e:
            print(f"Display Error: {e}")

    def cleanup(self):
        """Called when widget is destroyed or closed."""
        self._stop_loading_thread()
        try:
            self.plotter.close()
        except:
            pass

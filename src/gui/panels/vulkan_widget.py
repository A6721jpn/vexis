import time
import math
import numpy as np
from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QImage, QPixmap, QPainter
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QSizePolicy
import vexis_vulkan_core

class VulkanImageWidget(QWidget):
    """
    A custom QWidget that uses vexis_vulkan_core.VulkanRenderer to render 3D contours
    and handles mouse events for arcball/trackball camera rotation and zoom.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        # Use a label to display the image
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: #0f0f1a;")
        self.image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.image_label.setMinimumSize(0, 0)
        self.layout.addWidget(self.image_label, 1)
        
        # Renderer state
        self.renderer = None
        self._w = 0
        self._h = 0
        
        # Mesh data
        self.vertices = []  # Flat list of all vertices for rendering [x,y,z, x,y,z...] (Actually we send via flat coordinates but combined?)
        self.indices = []   # Flat list of triangle indices
        self.values = []    # Scalar values for each vertex
        self.min_val = 0.0
        self.max_val = 1.0
        
        # Camera state
        self.center = [0.0, 0.0, 0.0]
        self.base_scale = 1.0
        self.zoom_level = 1.0
        self.pitch = 0.0   # Rotation around X axis
        self.yaw = 0.0     # Rotation around Y axis
        
        # Mouse tracking
        self.last_pos = None
        
        self.data_ready = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        new_w = self.width()
        new_h = self.height()
        if new_w > 0 and new_h > 0 and (new_w != self._w or new_h != self._h):
            self._w = new_w
            self._h = new_h
            if self.renderer is None:
                try:
                    self.renderer = vexis_vulkan_core.VulkanRenderer(self._w, self._h)
                    if hasattr(self, 'vertices_base') and self.vertices_base:
                        self.renderer.set_mesh(self.vertices_base, self.indices)
                except Exception as e:
                    print(f"Failed to create VulkanRenderer: {e}")
            else:
                try:
                    self.renderer.resize(self._w, self._h)
                except Exception as e:
                    print(f"Failed to resize VulkanRenderer: {e}")
            self.update_render()

    def set_mesh_data(self, coords, indices):
        """
        Setup static mesh layout.
        coords: shape (N, 3) or flat list of (N * 3).
        indices: flat list of triangle indices.
        """
        if isinstance(coords, np.ndarray):
            coords = coords.tolist()
        
        # Ensure flat coordinates
        if len(coords) > 0 and isinstance(coords[0], (list, tuple)):
            self.vertices_base = [val for pt in coords for val in pt]
        else:
            self.vertices_base = coords
            
        self.indices = indices
        
        # Calc bounding box to set default camera
        if len(self.vertices_base) >= 3:
            xs = self.vertices_base[0::3]
            ys = self.vertices_base[1::3]
            zs = self.vertices_base[2::3]
            min_c = [min(xs), min(ys), min(zs)]
            max_c = [max(xs), max(ys), max(zs)]
            self.center = [(min_c[i] + max_c[i]) / 2.0 for i in range(3)]
            extent = max([max_c[i] - min_c[i] for i in range(3)])
            self.base_scale = 1.8 / extent if extent > 0 else 1.0
        
        self.zoom_level = 1.0
        self.pitch = 0.0
        self.yaw = 0.0

        if self.renderer is not None:
            try:
                self.renderer.set_mesh(self.vertices_base, self.indices)
            except Exception as e:
                print(f"Failed to set mesh in VulkanRenderer: {e}")

    def set_scalar_data(self, values, min_v, max_v):
        """Update colors/scalars for the mesh and render."""
        self.values = values
        self.min_val = min_v
        self.max_val = max_v
        self.data_ready = True
        self.update_render()

    def _build_mvp(self):
        """Construct Model-View-Projection matrix for Vulkan (Column-Major)."""
        scale = self.base_scale * self.zoom_level
        cp = math.cos(self.pitch)
        sp = math.sin(self.pitch)
        cy = math.cos(self.yaw)
        sy = math.sin(self.yaw)
        
        # R = Ry(yaw) * Rx(pitch)
        r00 = cy;  r01 = sy*sp; r02 = sy*cp
        r10 =  0;  r11 = cp;    r12 = -sp
        r20 = -sy; r21 = cy*sp; r22 = cy*cp
        
        # Translate center to origin
        cx, cy_c, cz = self.center
        
        tx = -(r00*cx + r01*cy_c + r02*cz) * scale
        ty = -(r10*cx + r11*cy_c + r12*cz) * scale
        # map Z to Vulkan depth range [0, 1] roughly.
        tz = -(r20*cx + r21*cy_c + r22*cz) * scale * 0.1 + 0.5
        
        return [
            [r00*scale, r10*scale, r20*scale*0.1, 0.0],
            [r01*scale, r11*scale, r21*scale*0.1, 0.0],
            [r02*scale, r12*scale, r22*scale*0.1, 0.0],
            [float(tx), float(ty), float(tz), 1.0]
        ]

    def update_render(self):
        if not self.data_ready or self.renderer is None or self._w == 0 or self._h == 0:
            return
            
        mvp = self._build_mvp()
        
        try:
            # Call Rust bindings
            frame_list = self.renderer.render_mesh(
                self.values,
                mvp,
                self.min_val,
                self.max_val
            )
            
            frame_bytes = bytes(frame_list)
            
            # Create QImage from bytes
            img = QImage(
                frame_bytes,
                self._w,
                self._h,
                QImage.Format_RGBA8888
            )
            pix = QPixmap.fromImage(img)
            self.image_label.setPixmap(pix)
        except Exception as e:
            print(f"Render failed: {e}")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.last_pos = event.position()

    def mouseMoveEvent(self, event):
        if self.last_pos is not None and event.buttons() & Qt.LeftButton:
            pos = event.position()
            dx = pos.x() - self.last_pos.x()
            dy = pos.y() - self.last_pos.y()
            
            # Adjust rotation (drag to rotate)
            self.yaw += dx * 0.01
            self.pitch += dy * 0.01
            
            self.last_pos = pos
            self.update_render()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.last_pos = None

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self.zoom_level *= 1.1
        else:
            self.zoom_level /= 1.1
        self.update_render()

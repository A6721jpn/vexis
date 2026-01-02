from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox, QWidget
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt
import os
import src.version as v

# ==========================================
#  EDIT ABOUT TEXT HERE
# ==========================================
ABOUT_TEXT_TEMPLATE = """
<h2 style='text-align:center;'>VEXIS-CAE</h2>
<p style='text-align:center; font-size:14px;'><b>Version {version}</b></p>
<hr>
<p><b>License:</b> {license}</p>
<p><b>Developer:</b> {author}</p>
<p>Please reach out to me if you find any bugs.</p>
"""
# ==========================================

class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About VEXIS-CAE")
        self.resize(500, 400) # Reasonable default size
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Logo Area
        # Logo Area
        logo_label = QLabel()
        
        import sys
        if getattr(sys, 'frozen', False):
            root_dir = os.path.dirname(sys.executable)
        else:
            root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            
        logo_path = os.path.join(root_dir, "doc", "VEXIS-CAE-LOGO-LARGE.png")
        
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            
            # High-DPI support:
            # Calculate target physical pixels based on logical width and device pixel ratio
            screen = self.screen()
            dpr = screen.devicePixelRatio() if screen else 1.0
            
            # Desired logical width (e.g. 400px on standard screen)
            logical_width = 450
            target_px = int(logical_width * dpr)
            
            scaled = pixmap.scaledToWidth(target_px, Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            
            logo_label.setPixmap(scaled)
            logo_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(logo_label)
        else:
            logo_label.setText("VEXIS-CAE")
            logo_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #555;")
            layout.addWidget(logo_label)
        
        # Text Area
        text_label = QLabel()
        text_label.setTextFormat(Qt.RichText)
        text_label.setText(ABOUT_TEXT_TEMPLATE.format(
            version=v.VERSION,
            license=v.LICENSE_NAME,
            author=v.AUTHOR
        ))
        text_label.setAlignment(Qt.AlignCenter)
        text_label.setOpenExternalLinks(True)
        layout.addWidget(text_label)
        
        # Spacer
        layout.addStretch()
        
        # Button
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

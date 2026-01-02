from PySide6.QtWidgets import QWidget, QVBoxLayout, QProgressBar, QLabel, QPlainTextEdit
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor

class ProgressPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._setup_ui()
        
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        self.title_label = QLabel("Analysis Progress")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self.title_label)
        
        self.status_label = QLabel("Status: Idle")
        layout.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        layout.addWidget(QLabel("Logs:"))
        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; font-family: Consolas, monospace;")
        layout.addWidget(self.log_area)

    def set_job_info(self, name, status_text, progress):
        self.title_label.setText(f"Analyzing: {name}")
        self.status_label.setText(f"Status: {status_text}")
        self.progress_bar.setValue(progress)

    def append_log(self, text):
        self.log_area.appendPlainText(text)
        self.log_area.moveCursor(QTextCursor.MoveOperation.End)

    def clear(self):
        self.log_area.clear()
        self.progress_bar.setValue(0)
        self.status_label.setText("Status: Idle")

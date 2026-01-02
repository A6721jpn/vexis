import sys
import os
from PySide6.QtWidgets import QApplication
from src.gui.main_window import MainWindow

def main():
    # Set plugin path if needed (sometimes required for PySide6)
    # os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = ...
    
    app = QApplication(sys.argv)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

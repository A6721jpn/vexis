import sys
import os
import datetime
import traceback
from PySide6.QtWidgets import QMessageBox

class DualLogger:
    """Writes to both stdout/stderr and a log file."""
    def __init__(self, filename, original_stream):
        self.terminal = original_stream
        self.log = open(filename, "a", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()

    def flush(self):
        self.terminal.flush()
        self.log.flush()

def setup_logging():
    """Sets up file logging with timestamped filename in 'logs' subdir."""
    # Determine root dir (exe location or script location)
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        # src/app_logger.py -> src -> root
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Create logs directory
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    # Generate filename: app_YYYYMMDD_HHMMSS.log
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"app_{timestamp}.log")

    # Redirect stdout/stderr
    sys.stdout = DualLogger(log_file, sys.stdout)
    sys.stderr = DualLogger(log_file, sys.stderr)
    
    print(f"Logging initialized. Log file: {log_file}")
    return log_file

def install_crash_handler():
    """Installs a global exception hook to catch crashes."""
    def exception_hook(exctype, value, tb):
        # Format the traceback
        err_msg = "".join(traceback.format_exception(exctype, value, tb))
        
        # Log to file (via stderr redirection)
        print("CRITICAL ERROR CAUGHT BY HANDLER:", file=sys.stderr)
        print(err_msg, file=sys.stderr)
        
        # Show GUI dialog
        # Note: We create a dummy app ref if needed, but usually QMessageBox works if App exists
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("Critical Error")
        msg.setText("An unexpected error occurred and the application must close.")
        msg.setInformativeText(f"{value}\n\nPlease check the logs folder for details.")
        msg.setDetailedText(err_msg)
        msg.exec()
        
        # Call original excepthook (usually just exits)
        sys.__excepthook__(exctype, value, tb)
        sys.exit(1)

    sys.excepthook = exception_hook

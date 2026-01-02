import sys
import os
import argparse
from PySide6.QtWidgets import QApplication

from PySide6.QtGui import QIcon

def resolve_path(relative_path):
    """
    リソースの絶対パスを解決する：
    1. PyInstaller _MEIPASS (同梱リソース)
    2. exeと同じフォルダ (外出しリソース - 現在のbuild.pyはこれ)
    3. 開発時のソースコード場所
    """
    if getattr(sys, "frozen", False):
        # 1. Check bundled (_MEIPASS)
        base_path = getattr(sys, "_MEIPASS", None)
        if base_path:
            p = os.path.join(base_path, relative_path)
            if os.path.exists(p):
                return p
        
        # 2. Check next to EXE
        base_path = os.path.dirname(sys.executable)
        p = os.path.join(base_path, relative_path)
        if os.path.exists(p):
            return p
            
        # Fallback: return path in exe dir even if not exists (for logging)
        return os.path.join(base_path, relative_path)

    # 3. Dev mode
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

def main():
    # Handle arguments for internal subprocess calls (Mesh Generation in frozen state)
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-mesh-gen", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--internal-config", help=argparse.SUPPRESS)
    parser.add_argument("--internal-stp", help=argparse.SUPPRESS)
    parser.add_argument("--internal-out", help=argparse.SUPPRESS)
    
    # Parse known args to capture internal flags, ignoring others (like Qt args)
    args, unknown = parser.parse_known_args()

    # 1. Internal Mesh Generation Mode (No GUI)
    if args.run_mesh_gen:
        from src.mesh_gen.main import generate_adaptive_mesh
        try:
            generate_adaptive_mesh(args.internal_config, args.internal_stp, args.internal_out)
        except Exception as e:
            print(f"Error in internal mesh gen: {e}")
            sys.exit(1)
        sys.exit(0)

    # 2. GUI Mode
    # Set plugin path if needed
    # os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = ...
    
    # --- Taskbar Icon Fix (AppUserModelID) ---
    import ctypes
    # Changed ID again to force refresh
    myappid = 'vexis_cae.gui.version.1.0.rev3' 
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass
    
    app = QApplication(sys.argv)
    
    # --- Resolve Paths ---
    icon_path = resolve_path("icon.ico")

    print("[icon] icon_path =", icon_path)
    print("[icon] exists   =", os.path.exists(icon_path))
    
    # --- Splash Screen Setup (Earliset possible) ---
    from PySide6.QtWidgets import QSplashScreen
    from PySide6.QtGui import QPixmap, QFont, QColor, QPainter, QBrush, QIcon
    from PySide6.QtCore import Qt
    
    # ... (Splash creation logic is same, skip re-typing full splash code if possible, but here we need to insert before splash)
    
    # ... (Splash creation logic is same, skip re-typing full splash code if possible, but here we need to insert before splash)
    
    logo_path = resolve_path(os.path.join("doc", "VEXIS-CAE-LOGO-LARGE.png"))
    
    # Create base dark pixmap (Splash Background)
    splash_width, splash_height = 600, 350
    splash_pix = QPixmap(splash_width, splash_height)
    splash_pix.fill(QColor("#202020")) # Dark Gray Background
    
    # Load Logo
    logo = QPixmap(logo_path)
    if not logo.isNull():
        target_width = 500
        logo = logo.scaledToWidth(target_width, Qt.SmoothTransformation)
        painter = QPainter(splash_pix)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        x = (splash_width - logo.width()) // 2
        y = (splash_height - logo.height()) // 2 - 20 
        painter.drawPixmap(x, y, logo)
        painter.end()
    
    splash = QSplashScreen(splash_pix, Qt.WindowStaysOnTopHint)
    splash.show()
    
    def show_message(msg):
        splash.showMessage(msg, Qt.AlignBottom | Qt.AlignCenter, Qt.white)
        app.processEvents()

    show_message("Initializing VEXIS-CAE Runtime...")
    
    # --- Set App Icon (With Debug & Fallback) ---
    # --- Set App Icon (With Debug & Fallback) ---
    app_icon = None
    icon_status = "Init"
    if os.path.exists(icon_path):
        app_icon = QIcon(icon_path)
        print("[icon] isNull =", app_icon.isNull())
        print("[icon] sizes  =", app_icon.availableSizes())

        # 重要：アプリ全体 + メインウィンドウの両方に設定（保険）
        app.setWindowIcon(app_icon)
        icon_status = "Loaded"
    else:
        print("[icon] icon.ico not found")
        icon_status = "Not Found"
        # Fallback to PNG logo if ICO fails
        if os.path.exists(logo_path):
            app.setWindowIcon(QIcon(logo_path))
            icon_status = "Fallback PNG"
        
    show_message(f"Environment Check: {icon_status}")
    
    # --- Lazy Import & Init ---
    try:
        import time
        from PySide6.QtCore import QTimer
        
        # Simulate slight delay if needed for visibility, or just proceed
        # time.sleep(0.5) 
        
        show_message("Loading User Interface Components...")
        from src.gui.main_window import MainWindow
        
        show_message("Setting up Analysis Environment...")
        # (Any other heavy init could go here)
        
        window = MainWindow()
        if app_icon is not None and not app_icon.isNull():
            window.setWindowIcon(app_icon)
        
        # When main window is ready
        window.show()
        
        # Fix: Delay splash finish to ensure window is fully painted and responsive
        # Wait 500ms after the event loop starts processing the show event
        QTimer.singleShot(700, lambda: splash.finish(window))
        
    except Exception as e:
        splash.showMessage(f"Error: {e}", Qt.AlignBottom | Qt.AlignCenter, Qt.red)
        app.processEvents()
        time.sleep(3)
        sys.exit(1)
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

import sys
import os
import argparse
from PySide6.QtWidgets import QApplication
from src.gui.main_window import MainWindow

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
    # Set plugin path if needed (sometimes required for PySide6)
    # os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = ...
    
    app = QApplication(sys.argv)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

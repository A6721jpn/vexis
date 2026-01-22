# === CLI Mode: Disable GUI/Graphics before any imports ===
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYVISTA_OFF_SCREEN", "true")
os.environ.setdefault("VTK_DEFAULT_OPENGL_WINDOW", "vtkOSOpenGLRenderWindow")
# =========================================================

import glob, sys, argparse
import yaml
import time
from tqdm import tqdm
import analysis_helpers as helpers

# Paths relative to the executable or script location
if getattr(sys, 'frozen', False):
    # Running as compiled EXE
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Running as Python script
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

INPUT_DIR = os.path.join(BASE_DIR, "input")
CONFIG_DIR = os.path.join(BASE_DIR, "config")
TEMP_DIR = os.path.join(BASE_DIR, "temp")
RESULT_DIR = os.path.join(BASE_DIR, "results")

CONFIG_FILE = os.path.join(CONFIG_DIR, "config.yaml")
MATERIAL_CONFIG = os.path.join(CONFIG_DIR, "material.yaml")
DEFAULT_TEMPLATE = os.path.join(BASE_DIR, "template2.feb")

def main():
    parser = argparse.ArgumentParser(description="VEXIS-CAE Auto Analysis Workflow")
    parser.add_argument("--mesh-only", action="store_true", help="Only run mesh generation, skip analysis.")
    parser.add_argument("--skip-mesh", action="store_true", help="Skip mesh generation, use existing .vtk in temp/ (matches step filename).")
    
    # Internal hidden arguments for meshing subprocess (frozen EXE support)
    parser.add_argument("--run-mesh-gen", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--internal-config", help=argparse.SUPPRESS)
    parser.add_argument("--internal-stp", help=argparse.SUPPRESS)
    parser.add_argument("--internal-out", help=argparse.SUPPRESS)
    
    args = parser.parse_args()

    # 0. Internal Mesh Generation Mode
    if args.run_mesh_gen:
        from src.mesh_gen.main import generate_adaptive_mesh
        generate_adaptive_mesh(args.internal_config, args.internal_stp, args.internal_out)
        return

    steps = glob.glob(os.path.join(INPUT_DIR, "*.stp")) + glob.glob(os.path.join(INPUT_DIR, "*.step"))
    
    # Show Logo using 'art' library
    try:
        from art import text2art
        print(text2art("VEXIS - CAE", font="doom").rstrip() + "\n")
    except ImportError:
        print("--- VEXIS-CAE Analysis Workflow ---")
    
    print(f"--- Auto Analysis Workflow ---")
    print(f"Target Files: {len(steps)} | Mode: {'Mesh-Only' if args.mesh_only else 'Skip-Mesh' if args.skip_mesh else 'Full'}")
    print(f"Controls: [s] = Skip current job, [Ctrl+C] = Stop all")

    with tqdm(steps, desc="Initializing...", position=0) as pbar:
        for step_path in pbar:
            base_name = os.path.basename(step_path)
            name_no_ext = os.path.splitext(base_name)[0]
            
            def update_status(m="-", p="-", s="-"):
                # Simplified status mapping: m=meshing, p=prep, s=solver
                pbar.set_description(f"{base_name[:20]:<20} [{m}]Mesh [{p}]Prep [{s}]Job")
                pbar.refresh()

            update_status()
            
            try:
                # --- CONFIG & PATHS ---
                material_yaml = MATERIAL_CONFIG
                mesh_config_path = CONFIG_FILE
                # --- CONFIG & PATHS ---
                material_yaml = MATERIAL_CONFIG
                mesh_config_path = CONFIG_FILE
                
                try:
                    from src.config_loader import AnalysisConfig
                    an_cfg = AnalysisConfig.from_yaml(CONFIG_FILE)
                    
                    push_dist = -1.0 * abs(an_cfg.total_stroke)
                    sim_steps = an_cfg.time_steps
                    mat_name = an_cfg.material_name
                    num_threads = an_cfg.num_threads
                    contact_penalty = an_cfg.contact_penalty
                    template_feb = an_cfg.template_feb
                    febio_path = an_cfg.febio_path if an_cfg.febio_path else None
                except Exception as e:
                    tqdm.write(f"\n! Configuration Error: {e}")
                    # Stop workflow if config is invalid
                    sys.exit(1)

                # 1. Mesh Gen
                vtk_path = os.path.join(TEMP_DIR, f"{name_no_ext}.vtk")
                if args.skip_mesh:
                    if not os.path.exists(vtk_path):
                        raise FileNotFoundError(f"Mesh not found for --skip-mesh: {vtk_path}")
                    update_status(m="s") # s for skipped
                else:
                    vtk_path = helpers.run_meshing(step_path, mesh_config_path, TEMP_DIR)
                    update_status(m="x")

                if args.mesh_only:
                    update_status(m="x", p="-", s="-")
                    continue

                # 2. FEBio Prep
                feb_path = os.path.join(TEMP_DIR, f"{name_no_ext}.feb")
                helpers.run_integration(vtk_path, template_feb, feb_path, push_dist, sim_steps, mat_name, material_yaml, contact_penalty=contact_penalty)
                update_status(m="x" if not args.skip_mesh else "s", p="x")

                # 3. Solver & Extraction
                success = helpers.run_solver_and_extract(feb_path, RESULT_DIR, num_threads=num_threads, febio_exe=febio_path)
                update_status(m="x" if not args.skip_mesh else "s", p="x", s="x" if success else "\033[91mE\033[0m")
                
            except KeyboardInterrupt:
                tqdm.write("\n! Stopping workflow (Ctrl+C).")
                break
            except Exception as e:
                tqdm.write(f"\n! ERROR in {base_name}: {e}")

    print(f"\nWorkflow Completed.")
    try:
        input("\nPress Enter to exit...")
    except (EOFError, KeyboardInterrupt):
        pass

if __name__ == "__main__":
    main()

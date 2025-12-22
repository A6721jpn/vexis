import os, glob, sys, argparse
import yaml
import time
from tqdm import tqdm
import analysis_helpers as helpers

# Paths relative to VEXIS-CAE/
# Default paths relative to VEXIS-CAE  /
INPUT_DIR = "input"
CONFIG_DIR = "config"
TEMP_DIR = "temp"
RESULT_DIR = "results"
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.yaml")
MATERIAL_CONFIG = os.path.join(CONFIG_DIR, "material.yaml")

def main():
    parser = argparse.ArgumentParser(description="VEXIS-CAE Auto Analysis Workflow")
    parser.add_argument("--mesh-only", action="store_true", help="Only run mesh generation, skip analysis.")
    parser.add_argument("--skip-mesh", action="store_true", help="Skip mesh generation, use existing .vtk in temp/ (matches step filename).")
    args = parser.parse_args()

    steps = glob.glob(os.path.join(INPUT_DIR, "*.stp")) + glob.glob(os.path.join(INPUT_DIR, "*.step"))
    
    # Show Logo using 'art' library
    try:
        from art import tprint
        tprint("VEXIS-CAE", font="doom")
    except ImportError:
        print("\n--- VEXIS-CAE Analysis Workflow ---")
    
    print(f"--- Auto Analysis Workflow ---\n")
    print(f"Target Files: {len(steps)} | Mode: {'Mesh-Only' if args.mesh_only else 'Skip-Mesh' if args.skip_mesh else 'Full'}\n")
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
                push_dist, sim_steps, mat_name, num_threads = None, 20, None, None
                template_feb = "template2.feb" # Default fallback
                febio_path = None # Will use helper default if not in config

                if os.path.exists(CONFIG_FILE):
                    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                        full_conf = yaml.safe_load(f)
                        conf = full_conf.get("analysis", {})
                        if "total_stroke" in conf: push_dist = -1.0 * abs(float(conf["total_stroke"]))
                        elif "push_dist" in conf: push_dist = float(conf["push_dist"])
                        sim_steps = conf.get("time_steps", sim_steps)
                        mat_name = conf.get("material_name")
                        num_threads = conf.get("num_threads")
                        template_feb = conf.get("template_feb", template_feb)
                        febio_path = conf.get("febio_path")

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
                helpers.run_integration(vtk_path, template_feb, feb_path, push_dist, sim_steps, mat_name, material_yaml)
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

if __name__ == "__main__":
    main()

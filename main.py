# === CLI Mode: Disable GUI/Graphics before any imports ===
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYVISTA_OFF_SCREEN", "true")
os.environ.setdefault("VTK_DEFAULT_OPENGL_WINDOW", "vtkOSOpenGLRenderWindow")
# =========================================================

import argparse
import glob
import sys

from tqdm import tqdm

import analysis_helpers as helpers

# Paths relative to the executable or script location
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

INPUT_DIR = os.path.join(BASE_DIR, "input")
CONFIG_DIR = os.path.join(BASE_DIR, "config")
TEMP_DIR = os.path.join(BASE_DIR, "temp")
RESULT_DIR = os.path.join(BASE_DIR, "results")

CONFIG_FILE = os.path.join(CONFIG_DIR, "config.yaml")
MATERIAL_CONFIG = os.path.join(CONFIG_DIR, "material.yaml")


def main():
    parser = argparse.ArgumentParser(description="VEXIS-CAE Auto Analysis Workflow")
    parser.add_argument(
        "--mesh-only",
        action="store_true",
        help="Only run mesh generation, skip analysis.",
    )
    parser.add_argument(
        "--skip-mesh",
        action="store_true",
        help="Skip mesh generation, use existing .vtk in temp/ (matches step filename).",
    )

    # Internal hidden arguments for meshing subprocess (frozen EXE support)
    parser.add_argument("--run-mesh-gen", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--internal-config", help=argparse.SUPPRESS)
    parser.add_argument("--internal-stp", help=argparse.SUPPRESS)
    parser.add_argument("--internal-out", help=argparse.SUPPRESS)

    args = parser.parse_args()

    if args.run_mesh_gen:
        from src.mesh_gen.main import generate_adaptive_mesh

        generate_adaptive_mesh(
            args.internal_config, args.internal_stp, args.internal_out
        )
        return

    from src.config_loader import AnalysisConfig

    steps = sorted(
        glob.glob(os.path.join(INPUT_DIR, "*.stp"))
        + glob.glob(os.path.join(INPUT_DIR, "*.step")),
        key=str.lower,
    )
    mode_label = (
        "Mesh-Only" if args.mesh_only else "Skip-Mesh" if args.skip_mesh else "Full"
    )

    analysis_config = None
    if not args.mesh_only:
        try:
            analysis_config = AnalysisConfig.from_yaml(CONFIG_FILE)
        except Exception as error:
            tqdm.write(f"\n! Configuration Error: {error}")
            sys.exit(1)

    try:
        from art import text2art

        print(text2art("VEXIS - CAE", font="doom").rstrip() + "\n")
    except ImportError:
        print("--- VEXIS-CAE Analysis Workflow ---")

    print("--- Auto Analysis Workflow ---")
    print(f"Target Files: {len(steps)} | Mode: {mode_label}")
    print("Controls: [s] = Skip current job, [Ctrl+C] = Stop all")

    with tqdm(steps, desc="Initializing...", position=0) as pbar:
        for step_path in pbar:
            base_name = os.path.basename(step_path)
            name_no_ext = os.path.splitext(base_name)[0]

            def update_status(m="-", p="-", s="-"):
                pbar.set_description(
                    f"{base_name[:20]:<20} [{m}]Mesh [{p}]Prep [{s}]Job"
                )
                pbar.refresh()

            update_status()

            try:
                vtk_path = os.path.join(TEMP_DIR, f"{name_no_ext}.vtk")
                if args.skip_mesh:
                    if not os.path.exists(vtk_path):
                        raise FileNotFoundError(
                            f"Mesh not found for --skip-mesh: {vtk_path}"
                        )
                    update_status(m="s")
                else:
                    vtk_path = helpers.run_meshing(step_path, CONFIG_FILE, TEMP_DIR)
                    update_status(m="x")

                if args.mesh_only:
                    update_status(m="x", p="-", s="-")
                    continue

                push_dist = -1.0 * abs(analysis_config.total_stroke)
                sim_steps = analysis_config.time_steps
                mat_name = analysis_config.material_name
                num_threads = analysis_config.num_threads
                contact_penalty = analysis_config.contact_penalty
                template_feb = analysis_config.template_feb
                febio_path = analysis_config.febio_path or None

                feb_path = os.path.join(TEMP_DIR, f"{name_no_ext}.feb")
                helpers.run_integration(
                    vtk_path,
                    template_feb,
                    feb_path,
                    push_dist,
                    sim_steps,
                    mat_name,
                    MATERIAL_CONFIG,
                    contact_penalty=contact_penalty,
                )
                update_status(m="x" if not args.skip_mesh else "s", p="x")

                success = helpers.run_solver_and_extract(
                    feb_path,
                    RESULT_DIR,
                    num_threads=num_threads,
                    febio_exe=febio_path,
                )
                update_status(
                    m="x" if not args.skip_mesh else "s",
                    p="x",
                    s="x" if success else "\033[91mE\033[0m",
                )

            except KeyboardInterrupt:
                tqdm.write("\n! Stopping workflow (Ctrl+C).")
                break
            except Exception as error:
                tqdm.write(f"\n! ERROR in {base_name}: {error}")

    print("\nWorkflow Completed.")
    try:
        input("\nPress Enter to exit...")
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    main()

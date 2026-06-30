import os
import sys
import shutil
import subprocess
import argparse
import time
import stat
import tempfile


def resolve_tool_python(src_base_dir):
    candidates = []

    venv_root = os.environ.get("VIRTUAL_ENV")
    if venv_root:
        candidates.append(
            os.path.join(
                venv_root,
                "Scripts" if os.name == "nt" else "bin",
                "python.exe" if os.name == "nt" else "python",
            )
        )

    candidates.append(
        os.path.join(
            src_base_dir,
            ".venv",
            "Scripts" if os.name == "nt" else "bin",
            "python.exe" if os.name == "nt" else "python",
        )
    )
    candidates.append(sys.executable)

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return os.path.abspath(candidate)

    return sys.executable


def copy_runtime_dir(src, dst, ignore=None, preserve_windows_runtime=False):
    if preserve_windows_runtime and os.name == "nt":
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        cmd = ["cmd.exe", "/c", "robocopy", src, dst, "/E"]
        if ignore is not None:
            cmd.extend(["/XF", "out.txt"])
        result = subprocess.run(cmd, check=False)
        if result.returncode >= 8:
            raise RuntimeError(f"robocopy failed for {src} -> {dst} with exit code {result.returncode}")
        return

    shutil.copytree(src, dst, ignore=ignore)

def build():
    parser = argparse.ArgumentParser(description="Build automation for VEXIS-CAE EXE (with experimental Rust core)")
    parser.add_argument("-o", "--output", help="Optional exact output directory for the distribution")
    parser.add_argument("-i", "--icon", help="Optional absolute path to an .ico file for the executable")
    args = parser.parse_args()

    # 1. Identify execution environment (Current worktree)
    SRC_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    project_name = "VEXIS-CAE-Rust"

    if args.output:
        dist_dir = os.path.abspath(args.output)
    else:
        dist_dir = os.path.join(SRC_BASE_DIR, "dist", project_name)
    dist_parent = os.path.dirname(dist_dir)

    print(f"--- Starting Build Process for {project_name} ---")
    print(f"  - Source: {SRC_BASE_DIR}")
    print(f"  - Destination: {dist_dir}")
    if args.icon:
        print(f"  - Icon: {os.path.abspath(args.icon)}")

    tool_python = resolve_tool_python(SRC_BASE_DIR)
    print(f"  - Tool Python: {tool_python}")

    # 0. Clean previous build (Robust)
    def remove_readonly(func, path, _):
        "Clear the readonly bit and reattempt the removal"
        os.chmod(path, stat.S_IWRITE)
        func(path)

    if os.path.exists(dist_dir):
        print(f"Cleaning previous build at {dist_dir}...")
        for i in range(5):
            try:
                shutil.rmtree(dist_dir, onerror=remove_readonly)
                break
            except OSError as e:
                print(f"  - Clean attempt {i+1} failed ({e}). Retrying...")
                time.sleep(1.0)
        else:
            print("Error: Could not clean output directory. Please close any files/folders open in that location.")
            sys.exit(1)

    # Auto-detect icon if not provided
    if not args.icon:
        modern_icon = os.path.join(SRC_BASE_DIR, "src", "icons", "icon.ico")
        default_icon = os.path.join(SRC_BASE_DIR, "icon.ico")
        
        if os.path.exists(modern_icon):
            args.icon = modern_icon
        elif os.path.exists(default_icon):
            args.icon = default_icon
            
        if args.icon:
            print(f"  - Icon (Auto-detected): {args.icon}")

    # Keep PyInstaller scratch/output out of the worktree so the repository
    # does not accumulate build debris.
    temp_root = tempfile.mkdtemp(prefix="vexis_rust_build_")
    pyinstaller_dist_parent = os.path.join(temp_root, "dist")
    pyinstaller_work_path = os.path.join(temp_root, "build")
    pyinstaller_bundle_dir = os.path.join(pyinstaller_dist_parent, project_name)
    pyinstaller_spec_file = os.path.join(SRC_BASE_DIR, "VEXIS-CAE-Rust.spec")

    # Build the Rust module before packaging (just to be safe)
    print("Step 1: Building Rust module vexis_vulkan_core via maturin...")
    rust_dir = os.path.join(SRC_BASE_DIR, "src", "libs", "vexis_vulkan_core")
    env = os.environ.copy()
    env["PYO3_USE_ABI3_FORWARD_COMPATIBILITY"] = "1"
    env["PATH"] = r"C:\Users\aokuni\.cargo\bin;" + env.get("PATH", "")
    try:
        subprocess.run(
            [tool_python, "-m", "maturin", "develop", "--release"],
            cwd=rust_dir, env=env, check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"Error: Maturin build failed with exit code {e.returncode}")
        print("Please ensure Rust is installed and you are in the correct Python environment.")
        sys.exit(1)

    print("Step 1b: Verifying Rust module import...")
    try:
        subprocess.run(
            [tool_python, "-c", "import vexis_vulkan_core; print('vexis_vulkan_core import ok')"],
            cwd=SRC_BASE_DIR,
            env=env,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Error: Rust module import verification failed with exit code {e.returncode}")
        sys.exit(1)

    # 2. PyInstaller execution
    print("Step 2: Running PyInstaller...")
    cmd = [
        tool_python, "-m", "PyInstaller",
        "--noconfirm",
        "--distpath", pyinstaller_dist_parent,
        "--workpath", pyinstaller_work_path,
        pyinstaller_spec_file,
    ]
    
    try:
        subprocess.run(cmd, cwd=SRC_BASE_DIR, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error: PyInstaller failed with exit code {e.returncode}")
        sys.exit(1)

    # 3. Configure distribution directory
    print("Step 3: Configuring distribution directory...")

    if not os.path.exists(pyinstaller_bundle_dir):
        print(f"Error: PyInstaller output not found: {pyinstaller_bundle_dir}")
        sys.exit(1)

    os.makedirs(dist_parent, exist_ok=True)
    shutil.copytree(pyinstaller_bundle_dir, dist_dir)
    print(f"  - Copied PyInstaller bundle")

    solver_dir = os.path.join(SRC_BASE_DIR, "solver")
    if not os.path.exists(solver_dir):
        fallback_solver_dir = os.path.abspath(os.path.join(SRC_BASE_DIR, "..", "..", "solver"))
        if os.path.exists(fallback_solver_dir):
            solver_dir = fallback_solver_dir

    dirs_to_copy = [
        (solver_dir, "solver", shutil.ignore_patterns("out.txt")),
        (os.path.join(SRC_BASE_DIR, "config"), "config", None),
        (os.path.join(SRC_BASE_DIR, "doc"), "doc", None),
        (os.path.join(SRC_BASE_DIR, "src", "icons"), os.path.join("src", "icons"), None),
        (os.path.join(SRC_BASE_DIR, "src", "gui", "styles"), os.path.join("src", "gui", "styles"), None),
    ]

    dirs_to_create = ["input", "results", "temp", "logs"]
    files_to_copy = ["template2.feb", "README.md", "LICENSE"]

    for src, rel_dst, ignore in dirs_to_copy:
        dst = os.path.join(dist_dir, rel_dst)
        if not os.path.exists(src):
            print(f"  - Warning: Source directory {rel_dst} not found.")
            continue
        copy_runtime_dir(
            src,
            dst,
            ignore=ignore,
            preserve_windows_runtime=(rel_dst == "solver"),
        )
        print(f"  - Copied {rel_dst}/")

    for d in dirs_to_create:
        dst = os.path.join(dist_dir, d)
        os.makedirs(dst, exist_ok=True)
        print(f"  - Created {d}/")

    for f in files_to_copy:
        src = os.path.join(SRC_BASE_DIR, f)
        dst = os.path.join(dist_dir, f)
        if not os.path.exists(src):
            print(f"  - Warning: Source file {f} not found.")
            continue
        shutil.copy2(src, dst)
        print(f"  - Copied {f}")

    print(f"\nBuild Completed successfully!")
    print(f"Distribution location: {dist_dir}")

if __name__ == "__main__":
    build()

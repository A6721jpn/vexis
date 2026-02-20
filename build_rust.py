import os
import sys
import shutil
import subprocess
import argparse
import time
import stat

def build():
    parser = argparse.ArgumentParser(description="Build automation for VEXIS-CAE EXE (with experimental Rust core)")
    parser.add_argument("-o", "--output", help="Optional output directory for the distribution (outside repository)")
    parser.add_argument("-i", "--icon", help="Optional absolute path to an .ico file for the executable")
    args = parser.parse_args()

    # 1. Identify execution environment (Current worktree)
    SRC_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    project_name = "VEXIS-CAE-Rust"
    
    if args.output:
        dist_parent = os.path.abspath(args.output)
        dist_dir = os.path.join(dist_parent, project_name)
    else:
        dist_parent = os.path.join(SRC_BASE_DIR, "dist")
        dist_dir = os.path.join(dist_parent, project_name)

    print(f"--- Starting Build Process for {project_name} ---")
    print(f"  - Source: {SRC_BASE_DIR}")
    print(f"  - Destination: {dist_dir}")
    if args.icon:
        print(f"  - Icon: {os.path.abspath(args.icon)}")

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

    # Build the Rust module before packaging (just to be safe)
    print("Step 1: Building Rust module vexis_vulkan_core via maturin...")
    rust_dir = os.path.join(SRC_BASE_DIR, "src", "libs", "vexis_vulkan_core")
    env = os.environ.copy()
    env["PYO3_USE_ABI3_FORWARD_COMPATIBILITY"] = "1"
    env["PATH"] = r"C:\Users\aokuni\.cargo\bin;" + env.get("PATH", "")
    try:
        subprocess.run(
            [sys.executable, "-m", "maturin", "develop", "--release"], 
            cwd=rust_dir, env=env, check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"Error: Maturin build failed with exit code {e.returncode}")
        print("Please ensure Rust is installed and you are in the correct Python environment.")
        sys.exit(1)

    # 2. PyInstaller execution
    print("Step 2: Running PyInstaller...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--distpath", dist_parent,
        "VEXIS-CAE-Rust.spec"
    ]
    
    try:
        subprocess.run(cmd, cwd=SRC_BASE_DIR, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error: PyInstaller failed with exit code {e.returncode}")
        sys.exit(1)

    # 3. Configure distribution directory
    print("Step 3: Configuring distribution directory...")
    
    dirs_to_copy = ["solver", "input", "config", "doc",
                    os.path.join("src", "icons"),
                    os.path.join("src", "gui", "styles"),
                    os.path.join("src", "libs"),
                    os.path.join("src", "utils")]

    dirs_to_create = ["results", "temp"]
    files_to_copy = ["template2.feb"]

    for d in dirs_to_copy:
        src = os.path.join(SRC_BASE_DIR, d)
        dst = os.path.join(dist_dir, d)
        if os.path.exists(src):
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            print(f"  - Copied {d}/")
        else:
            print(f"  - Warning: Source directory {d} not found.")

    for d in dirs_to_create:
        dst = os.path.join(dist_dir, d)
        os.makedirs(dst, exist_ok=True)
        print(f"  - Created {d}/")

    for f in files_to_copy:
        src = os.path.join(SRC_BASE_DIR, f)
        dst = os.path.join(dist_dir, f)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"  - Copied {f}")
        else:
            print(f"  - Warning: Source file {f} not found.")

    print(f"\nBuild Completed successfully!")
    print(f"Distribution location: {dist_dir}")

if __name__ == "__main__":
    build()

import os, subprocess, sys, yaml
import contextlib
import felupe as fe
import re
import msvcrt
import lxml.etree as ET
import time
from tqdm import tqdm

from src.mesh_gen.main import generate_adaptive_mesh
from src.mesh_swap.mesh_replacer import load_reference, replace_mesh, save_file
from src.mesh_swap.result_analysis.extract_results import process_log

# Determine global log path (could be passed in, but hardcoding relative to helper for now)
# Assuming run from Proto2/
from tqdm import tqdm

# We don't import generate_adaptive_mesh here anymore to avoid importing Gmsh in main process
# from src.mesh_gen.main import generate_adaptive_mesh
# from src.mesh_gen.main import generate_adaptive_mesh
from src.mesh_swap.mesh_replacer import load_reference, replace_mesh, save_file, adjust_keycap_height, override_rigid_bc, override_control_params
from src.mesh_swap.result_analysis.extract_results import process_log

# Determine global log path (could be passed in, but hardcoding relative to helper for now)
# Assuming run from Proto2/
GLOBAL_LOG_PATH = "workflow_detailed.log"

@contextlib.contextmanager
def redirect_output_to_file(log_path=GLOBAL_LOG_PATH):
    """
    Redirects Python-level stdout/stderr to a log file.
    Does NOT capture C-level output (like Gmsh), but safe for tqdm.
    """
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    
    with open(log_path, "a", encoding='utf-8') as f:
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        try:
            sys.stdout = f
            sys.stderr = f
            yield f
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr


def _get_simulation_total_time(feb_path):
    """ 
    Parses .feb file to calculate Total Simulation Time.
    Total Time = <time_steps> * <step_size>
    """
    try:
        # Use lxml for robust parsing
        tree = ET.parse(feb_path)
        root = tree.getroot()
        
        # Search anywhere for Control tag (handling nested steps)
        # FEBio spec v4.0 puts Control inside <step> or at root
        control = root.find(".//Control")
        
        # If not found via xpath (some ElementTree versions are limited), try explicit step iteration
        if control is None:
            for step in root.findall("step"):
                control = step.find("Control")
                if control is not None:
                    break
                    
        if control is not None:
            step_size_node = control.find("step_size")
            dt = float(step_size_node.text) if step_size_node is not None else 0.0
            
            time_steps_node = control.find("time_steps")
            steps = int(time_steps_node.text) if time_steps_node is not None else 0
            
            total_time = dt * steps
            return total_time if total_time > 0 else 1.0
            
        return 1.0 # Default/Fallback
    except Exception:
        return 1.0

def run_meshing(step_file, config, temp_dir):
    base_name = os.path.splitext(os.path.basename(step_file))[0]
    out_vtk = os.path.join(temp_dir, f"{base_name}.vtk")
    
    # Run Mesh Generation in Subprocess to capture C++ (Gmsh) output safely
    # This prevents Gmsh logs from leaking to console and avoids os.dup2 crashes
    cmd = [sys.executable, "-m", "src.mesh_gen.main", config, step_file, "-o", out_vtk]
    
    # Ensure log dir exists
    os.makedirs(os.path.dirname(os.path.abspath(GLOBAL_LOG_PATH)), exist_ok=True)
    
    with open(GLOBAL_LOG_PATH, "a", encoding="utf-8") as f_log:
        f_log.write(f"\n--- Meshing Log for {base_name} ---\n")
        f_log.flush()
        
        # We redirect both stdout and stderr to the log file
        try:
            subprocess.run(cmd, stdout=f_log, stderr=f_log, check=True)
        except subprocess.CalledProcessError as e:
            f_log.write(f"\n!!! Meshing Failed with code {e.returncode} !!!\n")
            raise RuntimeError(f"Meshing failed for {base_name}. Check {GLOBAL_LOG_PATH} for details.")
            
        f_log.write("-----------------------------------\n")
        
    return out_vtk


def run_integration(vtk_path, template, out_feb, push_dist_override=None, steps=None, material_name=None, material_config_path=None):
    with redirect_output_to_file():
        print(f"--- Integration Log for {vtk_path} ---")
        
        import meshio
        mesh_data = meshio.read(vtk_path)
        points = mesh_data.points
    
        cells_data = None
        cell_type_str = ""
        
        for block in mesh_data.cells:
            if block.type == "hexahedron27":
                cells_data = block.data[:, :20]
                cell_type_str = "hex20"
                break
            elif block.type == "hexahedron20":
                cells_data = block.data
                cell_type_str = "hex20" 
                break
                
        if cells_data is None: 
            for block in mesh_data.cells:
                if block.type == "hexahedron":
                    cells_data = block.data
                    cell_type_str = "hex8"
                    break
                
        if cells_data is None:
            raise ValueError(f"No hexahedron elements found in {vtk_path}.")
    
        tree = load_reference(template)
        
        # 1. Replace Mesh and get new height
        nodes_mapping, rubber_max_z = replace_mesh(tree, points, cells_data, "RUBBER_OBJ", cell_type_str)
        
        # 2. Adjust KEYCAP height to match rubber top (Ref=2.65 default)
        adjust_keycap_height(tree, rubber_max_z)
        
        # 3. Apply parameter overrides (Push Distance, Steps, Material)
        if push_dist_override is not None:
            override_rigid_bc(tree, push_dist_override)
            
        if steps is not None:
            override_control_params(tree, steps)
            
        if material_name and material_config_path:
            update_material_params(tree, material_name, material_config_path)

        save_file(tree, out_feb)
        print("-----------------------------------")

    return out_feb 

def run_solver_and_extract(feb_path, result_dir, num_threads=None, febio_exe=None):
    base_name = os.path.splitext(os.path.basename(feb_path))[0]
    
    # 1. Run Solver
    # Prepare environment with thread control
    env = os.environ.copy()
    if num_threads:
        env["OMP_NUM_THREADS"] = str(num_threads)
        print(f"  > Solver running with {num_threads} threads (OMP_NUM_THREADS)")

    log_name = f"{base_name}_log.txt"
    log_file = os.path.join(result_dir, log_name)
    
    # Use list for shell=False to avoid CMD output buffering
    if not febio_exe:
        febio_exe = r"C:\Program Files\FEBioStudio\bin\febio4.exe"
    
    cmd = [febio_exe, "-i", feb_path]

    total_time = _get_simulation_total_time(feb_path)
    
    # Unit is Time (float)
    solver_bar = tqdm(total=total_time, desc="Solver Time", position=1, leave=False, 
                      bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]")
    
    proc = None
    last_refresh_time = time.time()
    
    try:
        with open(log_file, "w") as f_log:
            # bufsize=1 means line buffered
            proc = subprocess.Popen(cmd, env=env, shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            
            # Iterate over stdout line by line as they arrive
            for line in proc.stdout:
                f_log.write(line) 
                
                # Update Progress Bar based on 'time = X' or 'time=X'
                if "time" in line:
                    # Match "time = 0.1" or "time=0.1", case-insensitive
                    match = re.search(r"time\s*=\s*([\d\.eE\+\-]+)", line, re.IGNORECASE)
                    if match:
                        try:
                            current_time = float(match.group(1))
                            solver_bar.n = current_time
                            solver_bar.last_print_n = current_time
                            solver_bar.refresh()
                            last_refresh_time = time.time()
                        except ValueError:
                            pass
                
                # Periodic forced refresh (every 2.0s)
                if time.time() - last_refresh_time > 2.0:
                    solver_bar.refresh()
                    last_refresh_time = time.time()
                
                # Check for 's' key skip (Windows only)
                if msvcrt.kbhit():
                    key = msvcrt.getch()
                    try:
                        key_char = key.decode().lower()
                    except:
                        key_char = ""
                    
                    if key_char == 's':
                        tqdm.write(f"\n  >>> 's' key pressed: Skipping current job ({base_name})...")
                        proc.kill()
                        raise KeyboardInterrupt("SkipJob")

        proc.wait() 
        
    except KeyboardInterrupt as e:
        if str(e) == "SkipJob":
            pass
        else:
            if proc: proc.kill()
            solver_bar.close()
            raise e
            
    finally:
        solver_bar.close()

    
    # 2. Extract Results
    # Give the OS a moment to release file handles after solver exit
    time.sleep(1.0) 

    with redirect_output_to_file():
        is_converged = False
        if os.path.exists(log_file):
            with open(log_file, "r") as f:
                log_content = f.read()
                # Check for standard and FEBio spaced format
                if "Normal termination" in log_content or "N O R M A L   T E R M I N A T I O N" in log_content:
                    is_converged = True
        
        src_data = os.path.join(os.path.dirname(feb_path), "rigid_body_data.txt")
        dst_data = os.path.join(result_dir, f"{base_name}_data.txt")
        
        if os.path.exists(src_data):
            # Retry loop for file move (Windows file locking issue)
            for attempt in range(5):
                try:
                    if os.path.exists(dst_data): 
                        os.remove(dst_data)
                    os.rename(src_data, dst_data)
                    break 
                except OSError as e:
                    if attempt < 4:
                        print(f"  [Retry {attempt+1}/5] Waiting for file release... ({src_data})")
                        time.sleep(1.0 + attempt)
                    else:
                        print(f"  ! Failed to move data file after retries: {e}")
                        raise e

            process_log(dst_data, result_dir)
        
        src_csv = os.path.join(result_dir, "force_displacement.csv")
        dst_csv = os.path.join(result_dir, f"{base_name}_result.csv")
        if os.path.exists(src_csv):
            if os.path.exists(dst_csv): os.remove(dst_csv)
            os.rename(src_csv, dst_csv)
            
        src_png = os.path.join(result_dir, "force_displacement.png")
        dst_png = os.path.join(result_dir, f"{base_name}_graph.png")
        if os.path.exists(src_png):
            if os.path.exists(dst_png): os.remove(dst_png)
            os.rename(src_png, dst_png)

def update_material_params(tree, material_name, yaml_path):
    """
    Overwrites the 'RUBBER' material parameters in the FEBio XML tree
    using definitions from the material.yaml file.
    """
    if not os.path.exists(yaml_path):
        print(f"Warning: Material config not found: {yaml_path}")
        return

    with open(yaml_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    if "materials" not in config or material_name not in config["materials"]:
        print(f"Warning: Material '{material_name}' not found in {yaml_path}")
        return
        
    mat_conf = config["materials"][material_name]
    print(f"Updating Material 'RUBBER' to: {material_name}")
    
    root = tree.getroot()
    # Find RUBBER material (usually id="1" or name="RUBBER")
    target_mat = None
    for mat in root.findall(".//material"):
        if mat.get("name") == "RUBBER":
            target_mat = mat
            break
            
    if target_mat is None:
        print("Warning: Material 'RUBBER' not found in template. Cannot update.")
        return
        
    # Update type if present
    if "type" in mat_conf:
        target_mat.set("type", mat_conf["type"])
        
    params = mat_conf.get("parameters", {})
    
    # helper to set or update text of sub-element
    def set_val(parent, tag, value):
        node = parent.find(tag)
        if node is None:
            node = ET.SubElement(parent, tag)
        node.text = str(value)

    # 1. Base parameters
    if "density" in params: set_val(target_mat, "density", params["density"])
    if "k" in params: set_val(target_mat, "k", params["k"])
    if "pressure_model" in params: set_val(target_mat, "pressure_model", params["pressure_model"])
    
    # 2. Viscoelastic (Standard format: t1-t6, g1-g6, g0)
    visco = params.get("visco", {})
    if visco:
        # Time constants
        t_list = visco.get("t", [])
        for i, val in enumerate(t_list):
            set_val(target_mat, f"t{i+1}", val)
        # Shear relaxation coefficients
        g_list = visco.get("g", [])
        for i, val in enumerate(g_list):
            set_val(target_mat, f"g{i+1}", val)
        
        if "g0" in visco:
            set_val(target_mat, "g0", visco["g0"])

    # 3. Elastic (Sub-element)
    el_conf = params.get("elastic", {})
    if el_conf:
        elastic_node = target_mat.find("elastic")
        if elastic_node is None:
            elastic_node = ET.SubElement(target_mat, "elastic")
        
        if "type" in el_conf:
            elastic_node.set("type", el_conf["type"])
            
        # Ogden specific: c1-c6, m1-m6
        c_list = el_conf.get("c", [])
        for i, val in enumerate(c_list):
            set_val(elastic_node, f"c{i+1}", val)
            
        m_list = el_conf.get("m", [])
        for i, val in enumerate(m_list):
            set_val(elastic_node, f"m{i+1}", val)
            
        # Generic support: other parameters in el_conf that are not 'type', 'c', 'm'
        for key, val in el_conf.items():
            if key not in ["type", "c", "m"]:
                set_val(elastic_node, key, val)

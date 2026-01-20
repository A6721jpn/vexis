import os, subprocess, sys, yaml
import contextlib
import felupe as fe
import re
import msvcrt
import lxml.etree as ET
import time
from tqdm import tqdm

# Helper modules
from src.mesh_swap.mesh_replacer import load_reference, replace_mesh, save_file, adjust_keycap_height, override_rigid_bc, override_control_params
from src.mesh_swap.result_analysis.extract_results import process_log

# Determine base directory for absolute paths
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_TEMPLATE = os.path.join(BASE_DIR, "template2.feb")

def get_solver_status():
    """
    Check solver availability and return status tuple.
    Returns: (status_text, is_found)
        - ("Embedded", True) if bundled solver exists
        - ("External", True) if external solver exists
        - ("Solver Not Found", False) if no solver found
    """
    bundled_path = os.path.join(BASE_DIR, "solver", "febio4.exe")
    if os.path.exists(bundled_path):
        return ("Embedded", True)
    
    # Check config.yaml for febio_path
    config_path = os.path.join(BASE_DIR, "config", "config.yaml")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            analysis = config.get("analysis", {})
            febio_path = analysis.get("febio_path")
            if febio_path and os.path.exists(febio_path):
                return ("External", True)
        except:
            pass
    
    # Check environment variable
    env_path = os.environ.get("FEBIO_PATH")
    if env_path and os.path.exists(env_path):
        return ("External", True)
    
    # Check default system path
    system_path = r"C:\Program Files\FEBioStudio\bin\febio4.exe"
    if os.path.exists(system_path):
        return ("External", True)
    
    return ("Solver Not Found", False)

@contextlib.contextmanager
def redirect_output_to_file(log_path):
    """
    Redirects Python-level stdout/stderr to a log file.
    Does NOT capture C-level output (like Gmsh), but safe for tqdm.
    """
    if log_path:
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
    else:
        yield sys.stdout


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

def run_meshing(step_file, config, temp_dir, log_path=None, log_callback=None, check_stop_callback=None):
    base_name = os.path.splitext(os.path.basename(step_file))[0]
    out_vtk = os.path.join(temp_dir, f"{base_name}.vtk")
    
    if getattr(sys, 'frozen', False):
        cmd = [sys.executable, "--run-mesh-gen", "--internal-config", config, "--internal-stp", step_file, "--internal-out", out_vtk]
    else:
        cmd = [sys.executable, "-m", "src.mesh_gen.main", config, step_file, "-o", out_vtk]
    
    # os.makedirs(os.path.dirname(os.path.abspath(GLOBAL_LOG_PATH)), exist_ok=True)
    
    if log_path:
        with open(log_path, "a", encoding="utf-8") as f_log:
            f_log.write(f"\n--- Meshing Log for {base_name} ---\n")
            f_log.flush()
            
            try:
                # Use Popen to capture logs in real-time for GUI
                # Use CREATE_NO_WINDOW to hide blank console on Windows
                cflags = 0
                if os.name == 'nt':
                    cflags = 0x08000000 # CREATE_NO_WINDOW

                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                    text=True, bufsize=1, 
                    creationflags=cflags
                )

                for line in proc.stdout:
                    if check_stop_callback and check_stop_callback():
                        proc.kill()
                        f_log.write("\n!!! Meshing Stopped by User !!!\n")
                        raise KeyboardInterrupt("SkipJob")

                    f_log.write(line)
                    if log_callback:
                        log_callback(line.strip())
                proc.wait()
                if proc.returncode != 0:
                    raise subprocess.CalledProcessError(proc.returncode, cmd)
            except Exception as e:
                f_log.write(f"\n!!! Meshing Failed: {e} !!!\n")
                raise RuntimeError(f"Meshing failed for {base_name}.")
                
            f_log.write("-----------------------------------\n")
    else:
        # Fallback if no log path provided (CLI mode mostly)
         subprocess.run(cmd, check=True)
        
    return out_vtk
        
    return out_vtk


def run_integration(vtk_path, template, out_feb, push_dist_override=None, steps=None, material_name=None, material_config_path=None, contact_penalty=None, log_path=None):
    with redirect_output_to_file(log_path):
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

        if contact_penalty is not None:
             update_contact_penalty(tree, contact_penalty)

        save_file(tree, out_feb)
        print("-----------------------------------")

    return out_feb 

def run_solver_and_extract(feb_path, result_dir, log_path=None, num_threads=None, febio_exe=None, log_callback=None, progress_callback=None, check_stop_callback=None):
    base_name = os.path.splitext(os.path.basename(feb_path))[0]
    work_dir = os.path.dirname(feb_path) # Temp directory
    
    env = os.environ.copy()
    if num_threads:
        env["OMP_NUM_THREADS"] = str(num_threads)

    # Priority list of solver candidates
    solver_candidates = []
    
    # 1. Bundled solver (always try first)
    bundled_path = os.path.join(BASE_DIR, "solver", "febio4.exe")
    solver_candidates.append(bundled_path)
    
    # 2. Config path (passed via febio_exe argument from job_manager)
    if febio_exe and febio_exe not in solver_candidates:
        solver_candidates.append(febio_exe)
        
    # 3. Environment variable
    if os.environ.get("FEBIO_PATH"):
        env_path = os.environ["FEBIO_PATH"]
        if env_path not in solver_candidates:
            solver_candidates.append(env_path)
        
    # 4. Default System Path
    system_path = r"C:\Program Files\FEBioStudio\bin\febio4.exe"
    if system_path not in solver_candidates:
        solver_candidates.append(system_path)

    # Filter out non-existent if they are just strings (except the last one as placeholder)
    # We keep the system_path even if it doesn't exist, as a last resort to try.
    valid_candidates = [p for p in solver_candidates if os.path.exists(p)]
    if not valid_candidates and os.path.exists(system_path): # If all others are gone, but system path exists
        valid_candidates = [system_path]
    elif not valid_candidates: # If nothing exists, just try the bundled path as a default
        valid_candidates = [bundled_path]
    
    # Ensure unique candidates and order
    valid_candidates = list(dict.fromkeys(valid_candidates))

    total_time = _get_simulation_total_time(feb_path)
    
    solver_bar = None
    if not progress_callback:
        solver_bar = tqdm(total=total_time, desc="Solver Time", position=1, leave=False, 
                          bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]")
    
    proc = None
    last_refresh_time = time.time()
    
    cflags = 0
    if os.name == 'nt':
        cflags = 0x08000000 # CREATE_NO_WINDOW

    
    try:
        # Open combined log file
        f_global = open(log_path, "a", encoding="utf-8") if log_path else open(os.devnull, "w")
        
        try:
            f_global.write(f"\n--- Solver Log for {base_name} ---\n")
            f_global.flush()

            # --- Execution Loop ---
            last_error_code = 0
            
            for current_exe in valid_candidates:
                cmd = [current_exe, "-i", feb_path]
                
                # Ensure current_exe's dir is in PATH for its own DLLs
                exe_dir = os.path.dirname(os.path.abspath(current_exe))
                current_env = env.copy()
                if exe_dir not in current_env.get("PATH", ""):
                    current_env["PATH"] = exe_dir + os.pathsep + current_env.get("PATH", "")

                f_global.write(f"DEBUG: Trying Solver = {current_exe}\n")
                f_global.write(f"DEBUG: CMD = {cmd}\n")
                f_global.write(f"DEBUG: CWD (Temp) = {work_dir}\n")
                f_global.flush()

                try:
                    proc = subprocess.Popen(
                        cmd, 
                        env=current_env,
                        stdout=subprocess.PIPE, 
                        stderr=subprocess.STDOUT, 
                        cwd=work_dir, # Run in temp dir
                        text=True, 
                        bufsize=1,
                        creationflags=cflags
                    )
                    
                    # Read and log output
                    for line in proc.stdout:
                        # Check external stop request (GUI)
                        if check_stop_callback and check_stop_callback():
                            proc.kill()
                            f_global.write("!!! Solver Stopped by User !!!\n")
                            return False

                        f_global.write(line) # Unified log
                        if log_callback:
                            log_callback(line.strip())

                        # Update Progress
                        if "time" in line:
                            match = re.search(r"time\s*=\s*([\d\.eE\+\-]+)", line, re.IGNORECASE)
                            if match:
                                try:
                                    current_time = float(match.group(1))
                                    if progress_callback:
                                        percent = int((current_time / total_time) * 100) if total_time > 0 else 0
                                        progress_callback(min(percent, 99))
                                    elif solver_bar:
                                        solver_bar.n = current_time
                                        solver_bar.refresh()
                                    last_refresh_time = time.time()
                                except ValueError:
                                    pass
                        
                        if solver_bar and time.time() - last_refresh_time > 2.0:
                            solver_bar.refresh()
                            last_refresh_time = time.time()
                    
                    proc.wait()
                    last_error_code = proc.returncode
                    f_global.write(f"DEBUG: Solver Finished with Return Code = {last_error_code}\n")
                    f_global.flush()

                    if last_error_code == 0:
                        break # Success!
                    
                    # If failed with DLL error, try next candidate
                    if last_error_code == 3221225781: # 0xC0000135 = STATUS_DLL_NOT_FOUND
                        f_global.write(f"!!! DLL NOT FOUND for {current_exe}. Trying next candidate... !!!\n")
                        continue
                    
                    # Other errors
                    break # Non-DLL error, stop trying candidates

                except Exception as e:
                    f_global.write(f"!!! Popen Failed for {current_exe}: {e} !!!\n")
                    f_global.flush()
                    # Try next candidate
                    continue
            
            if last_error_code != 0:
                return False

        finally:
             if f_global: f_global.close()
            
    except Exception as e:
        if proc and proc.poll() is None:
            proc.kill()
        if solver_bar: solver_bar.close()
        
        # Log error to global log if possible
        try:
             with open(log_path, "a", encoding="utf-8") as f_err:
                f_err.write(f"!!! Solver Exception: {str(e)} !!!\n")
        except:
            pass

        if isinstance(e, KeyboardInterrupt) and str(e) == "SkipJob":
            return False
        
        if not progress_callback: # CLI
             print(f"Solver error: {e}")
        
        # Re-raise if it's not a handled skip
        if isinstance(e, KeyboardInterrupt) and str(e) != "SkipJob":
            raise e
        
        # For GUI worker to catch
        raise e
    finally:
        if proc and proc.poll() is None:
            proc.kill()
        if solver_bar: solver_bar.close()


    
    # 2. Extract Results
    time.sleep(1.0) 
    
    # Data check in Unified Log
    # In unified mode, we don't parse a separate log file for "Normal Termination".
    # We rely on proc.returncode == 0 checked above.
    
    with redirect_output_to_file(log_path):
        # src_dir is now the same as work_dir (temp)
        # Helper for file rotation/movement with retries
        def safe_move(src, dst):
            if not os.path.exists(src): return
            for i in range(5):
                try:
                    if os.path.exists(dst): os.remove(dst)
                    os.rename(src, dst)
                    return
                except OSError: time.sleep(1.0 + i)
            tqdm.write(f"  ! Failed to move {os.path.basename(src)}")

        # Looking for data file in work_dir (temp)
        data_file_name = "rigid_body_data.txt" # Default name from template
        data_file_path = os.path.join(work_dir, data_file_name)
        
        # If not found there, check if it somehow ended up in result_dir (CWD usually, but we set CWD to work_dir)
        if not os.path.exists(data_file_path):
             # Fallback check
             fallback_path = os.path.join(result_dir, data_file_name)
             if os.path.exists(fallback_path):
                  data_file_path = fallback_path

        # If still not found, check extraction logic
        if not os.path.exists(data_file_path):
             print(f"! Data file not found: {data_file_path}")
             return False

        # Move to result dir with new name for processing
        target_data_path = os.path.join(result_dir, f"{base_name}_data.txt")
        safe_move(data_file_path, target_data_path)
        
        if os.path.exists(target_data_path):
            process_log(target_data_path, result_dir)
            safe_move(os.path.join(result_dir, "force_displacement.csv"), os.path.join(result_dir, f"{base_name}_result.csv"))
            safe_move(os.path.join(result_dir, "force_displacement.png"), os.path.join(result_dir, f"{base_name}_graph.png"))

    return True

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

def update_contact_penalty(tree, penalty_value):
    """
    Updates the penalty parameter for RUBBER_SELF_CONTACT.
    """
    if penalty_value is None:
        return

    print(f"Updating RUBBER_SELF_CONTACT penalty to: {penalty_value}")
    root = tree.getroot()
    
    # Search for the contact definition
    target_contact = None
    for contact in root.iter("contact"):
        if contact.get("name") == "RUBBER_SELF_CONTACT":
            target_contact = contact
            break
            
    if target_contact is None:
        print("Warning: Contact 'RUBBER_SELF_CONTACT' not found in template.")
        return
        
    # Update penalty
    penalty_node = target_contact.find("penalty")
    if penalty_node is None:
        penalty_node = ET.SubElement(target_contact, "penalty")
    
    penalty_node.text = str(penalty_value)


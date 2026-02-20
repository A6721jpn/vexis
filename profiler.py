import time
import os
from src.utils.xplt_loader import WaffleironLoader

def profile_loader():
    target_file = r"c:\github_repo\vexis\temp\example_1.xplt"
    if not os.path.exists(target_file):
        print(f"Error: {target_file} not found.")
        return

    print("Profiling WaffleironLoader performance...")
    print(f"File size: {os.path.getsize(target_file) / (1024**2):.2f} MB\n")

    # 1. Initialization (Parse binary structure & build indices)
    t0 = time.time()
    loader = WaffleironLoader(target_file)
    t1 = time.time()
    print(f"[Timer] __init__ (parsing & indices): {t1 - t0:.3f} seconds")
    
    # 2. Get Mesh (Create PyVista UnstructuredGrid)
    t2 = time.time()
    mesh = loader.get_mesh()
    t3 = time.time()
    print(f"[Timer] get_mesh (UnstructuredGrid creation): {t3 - t2:.3f} seconds")
    print(f"        Points: {mesh.n_points}, Cells: {mesh.n_cells}")

    # 3. Preload Steps (Parse step data into NumPy arrays)
    t4 = time.time()
    loader.preload_steps(progress_callback=lambda msg: None)
    t5 = time.time()
    num_steps = len(loader.xplt_data.step_blocks)
    print(f"[Timer] preload_steps ({num_steps} steps): {t5 - t4:.3f} seconds")
    
    # 4. Load Step Result & Render Simulation (time to set point/cell data)
    t6 = time.time()
    for i in range(min(5, num_steps)):
        loader.load_step_result(mesh, i)
        if "Effective stress" in mesh.cell_data:
            loader.domain_scalar_to_point(mesh.cell_data["Effective stress"])
    t7 = time.time()
    print(f"[Timer] Assigning data and averaging (5 frames): {t7 - t6:.3f} seconds")
    
    print("\nSummary:")
    print(f"Total time spent just loading to memory: {t5 - t0:.3f} seconds")

if __name__ == "__main__":
    profile_loader()

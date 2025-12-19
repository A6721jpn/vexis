# Proto3 Development Guide

**Version:** 3.0 (Clean Baseline)  
**Date:** 2025-12-18

This document describes the architecture, implementation details, and design philosophy of the **Proto3** Automated Analysis System. It is intended for development engineers to quickly understand the codebase and perform modifications.

---

## 1. System Overview

**Proto2** is an automation pipeline designed to perform Finite Element Analysis (FEA) on rubber keycap geometries. It automates the entire loop from raw CAD (STEP file) to Simulation Results (`.csv`/`.png`).

### Core Workflow
1.  **Input**: CAD files (`.stp`) placed in `input/`.
2.  **Mesh Generation**: Converts STEP to high-quality unstructured/structured hybrid mesh (`.vtk`).
3.  **FEBio Preparation**:
    *   Loads a template file (`template.feb`) which contains the physics, materials, and boundary conditions.
    *   **Swaps** the old mesh in the template with the new mesh generated from the CAD.
    *   **Reconstructs** NodeSets and Surfaces based on geometric rules (since IDs change).
    *   **Aligns** the new mesh to the correct coordinate position.
4.  **Solver Execution**: Runs `FEBio` solver in a monitored subprocess.
5.  **Result Extraction**: Parses log files to extract Force-Displacement curves.

---

## 2. Directory Structure

```text
Proto2/
├── main.py                 # Entry point. Handles UI and high-level flow.
├── analysis_helpers.py     # Worker functions (Mesh/Prep/Solver/Extract).
├── template.feb            # Master FEBio simulation setup (physics-only).
├── input/                  # Place .stp files here.
├── results/                # Outputs go here.
├── settings/               # Config files for Meshing.
└── src/
    ├── mesh_gen/           # [Submodule] Mesh Generation (Felupe/Gmsh)
    └── mesh_swap/          # [Submodule] XML Manipulation & Geometry Logic
        ├── mesh_replacer.py      # Core mesh replacement & alignment logic
        ├── set_reconstructor.py  # Face/Node set reconstruction logic
        └── geometry_utils.py     # Geometric predicates (is_bottom, is_outer, etc.)
```

---

## 3. Key Components & Implementation Details

### 3.1. Main Controller (`main.py`)
*   **Role**: UI Orchestrator.
*   **Features**:
    *   **Parallel Progress Bars**: Displays a checklist `[ ]Mesh [ ]Prep [ ]Slvr` for the current file + an overall progress bar.
    *   **Non-Blocking UI**: Uses `time.sleep(0.1)` and `pbar.refresh()` to ensure the UI updates even during heavy processing.

### 3.2. Helpers (`analysis_helpers.py`)
*   **Role**: Bridge between Python and External Tools.
*   **Key Implementations**:
    *   **`run_meshing`**: Executes `src.mesh_gen.main` in a **Subprocess**.
        *   *Reason*: Gmsh (C++ library) outputs noise that conflicts with Python's `tqdm` progress bar. Subprocessing isolates this into `workflow_detailed.log`.
    *   **`run_solver_and_extract`**: Runs FEBio (`febio4.exe`).
        *   Uses `subprocess.Popen` with `shell=False` and `bufsize=1` (Line Buffered) for **Real-Time Log Streaming**.
        *   **Parser**: regex-matches `time=` or `time =` to update the progress bar incrementally.
        *   **Total Time**: Recursively searches `template.feb` for `<Control>` tags (even nested in `<step>`) to calculate `{total_time} = {steps} * {dt}` correctly.

### 3.3. Mesh Gen (`src/mesh_gen/`)
*   **Role**: Generates a hybrid mesh (Hex/Tet) from STEP.
*   **Engine**: `gmsh` api via `felupe`.
*   **Output**: `.vtk` file.

### 3.4. Mesh Swap (`src/mesh_swap/`)

This is the most complex logic in Proto2. It resides in `mesh_replacer.py`.

#### A. Mesh Alignment (Min-XYZ Match)
When a new mesh is injected, its coordinate system might differ from the template.
*   **Logic**:
    1.  Calculate determining bounding box minimum (Min-X, Min-Y, Min-Z) of the **Old Mesh** in the template.
    2.  Calculate the same for the **New Mesh**.
    3.  Compute `Shift Vector = Old_Min - New_Min`.
    4.  Apply this translation to all nodes in the new mesh.
*   **Result**: The new mesh is placed exactly at the same "origin corner" as the old one. (No "Centroid" alignment, no manual offsets).

#### B. Set Reconstruction (`set_reconstructor.py`)
Since Node IDs and Element IDs change completely, we cannot rely on ID lists. We reconstruct NodeSets and Surfaces based on **Geometric Rules**.

*   **Strategy A (Relative Bounds)**:
    *   Used for: **Self-Contact** surfaces on the *same part*.
    *   Logic: Defines a bounding box relative to the mesh's current dimensions (e.g., "Top 20% of the geometry").
    *   *Why*: Distinguishes specific regions (like the "inside fold") that are geometrically distinct but adjacent.
    *   **Fix implemented**: If a contact pair's Secondary Surface is on the *same part* as the Primary, Strategy A is forced.

*   **Strategy B (Proximity / Raycasting)**:
    *   Used for: Interaction between *different parts* (e.g., Keycap vs Underlying Switch).
    *   Logic: Findings faces that are "close enough" to the target partner part.

*   **Geometric Rules**:
    *   `RUBBER_BOTTOM_CONTACTPrimary`: Uses rule `z_down_except_bottom`.
    *   Logic: Selects all downward-facing normal vectors, *excluding* faces that lie exactly on the Z-min plane. (Captures filleted edges/chamfers but avoids the flat bottom).

---

## 4. How to Modify (For Engineers)

### If you need to change Mesh Resolution:
*   Edit `settings/mesh_gen_adaptive_v6a.config`.

### If you need to change Physics (Material, Boundary Conditions):
*   Edit `template.feb` directly using FEBio Studio or a Text Editor.
*   **Note**: Do NOT change the names of Named Selections (NodeSets/Surfaces) in the template if you rely on the Reconstructor logic to find them.

### If you need to change Output/Logging:
*   Real-time console format: Edit `main.py` -> `update_status`.
*   FEBio Log parsing: Edit `analysis_helpers.py` -> `run_solver_and_extract`.

### If you observe "Negative Jacobian" or Contact Errors:
*   Check `src/mesh_swap/set_reconstructor.py`.
*   Verify if **Strategy A** (Explicit Bounds) needs to be adjusted for your new geometry shape. The "Relative Bounds" might need tuning if the aspect ratio of the keycap changes drastically.

---

## 5. Known Constraints

*   **Windows Only**: The "Job Skip" feature (`msvcrt`) is Windows-specific.
*   **File Naming**: Input files must be `.stp` or `.step`.
*   **Template Dependency**: The logic assumes the `template.feb` contains a valid mesh block named `RUBBER` (or the part name matches) to serve as a reference for alignment.

---
*End of Guide*

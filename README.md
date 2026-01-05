# VEXIS CAE
![Force-Stroke Graph Example](doc/VEXIS-CAE-LOGO-LARGE_black.png)

VEXIS CAE is an automated Finite Element Analysis (FEA) pipeline designed for large-deformation and buckling simulations of rubber dome, typically for membrane keyboard. It streamlines the workflow from raw CAD models (.step) to analyzed simulation results.

This software is licensed under the [GNU GPL v3](LICENSE).

## Key Features

- **Adaptive Mesh Generation**: Automatically creates high-quality hybrid meshes (Hex/Tet) from STEP files.
- **Modern GUI**: A polished, dark-themed interface built with PySide6.
    - **Live Preview**: Intearctive 3D visualization of mesh and simulation results.
    - **Real-time Monitoring**: Track solver progress and batch status visually.
- **Robustness**:
    - **Crash Handler**: Catches and logs unexpected errors safely.
    - **Logging**: Automatic file logging to `logs/` directory for troubleshooting.
- **FEBio Integration**: Seamlessly handles mesh swapping and solver execution.
- **Result Extraction**: Generates Force-Displacement curves (`.csv`) and plots (`.png`).

## Core Workflow

1.  **Input**: Place `.stp` or `.step` files in the `input/` directory (or drag & drop in GUI).
2.  **Meshing**: The system converts CAD geometry into a `.vtk` mesh optimized for stability.
3.  **Preparation**: The new mesh is injected into a `template.feb` file with automatic reconstruction.
4.  **Solver**: Executes the FEBio solver with real-time feedback.
5.  **Output**: Simulation results (Graph PNG, CSV Data, Log) are saved in `results/`.

## Getting Started

### Prerequisites

- Windows OS
- [FEBio Studio](https://febio.org/) (FEBio4 solver installed and in PATH)

### Quick Start (GUI)

1.  Run the application:
    ```bash
    python gui_main.py
    ```
    *(Or launch the built `VEXIS-CAE.exe`)*
2.  Place your CAD file (`.stp`) in the `input/` folder. It will appear in the job list automatically.
3.  Click **Start Batch** to begin analysis.
4.  Once complete, select the job to view the **Force-Stroke Graph** and **3D Results**.

### Quick Start (CLI)

For headless automation:
```bash
python main.py
```

## Documentation

For more detailed information, please refer to the following documents:
- [User Guide](doc/user_guide.html): General usage and troubleshooting.
- [GUI Reference Manual (JA)](doc/gui_reference_ja.md): Detailed explanation of GUI elements.


---
*Vexis is currently optimized for rubber keycap buckling analysis.*

Copyright (c) 2024-2025 A.O.
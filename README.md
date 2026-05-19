<table>
  <tr>
    <th align="center"><code>ALERT</code></th>
  </tr>
  <tr>
    <td align="center">
      <h1>実験実装：取り扱い注意</h1>
    </td>
  </tr>
</table>

# VEXIS CAE
![Force-Stroke Graph Example](doc/VEXIS-CAE-LOGO-LARGE_black.png)

VEXIS CAE is an automated Finite Element Analysis (FEA) pipeline designed for large-deformation and buckling simulations of rubber dome, typically for membrane keyboard. It streamlines the workflow from raw CAD models (.step) to analyzed simulation results.

This software is licensed under the [GNU GPL v3](LICENSE).

## Key Features

- **Adaptive Mesh Generation**: Automatically creates high-quality hybrid meshes (Hex/Tet) from STEP files.
- **Modern GUI**: A polished, dark-themed interface built with PySide6.
    - **Live Preview**: Interactive 3D visualization of mesh and simulation results.
    - **Real-time Monitoring**: Track solver progress and batch status visually.
    - **Mesh-Only Mode**: Generate and preview meshes without running solver via "Gen Mesh" button.
    - **Anti-Sleep**: Prevent PC sleep during long batch analyses with one-click toggle.
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

VEXIS can be run in two ways. Use the source route when developing or when you
clone this repository directly. Use the packaged route when you want to launch a
prebuilt Windows application.

### Option A: Run from Source

Use this route after cloning the repository.

#### Prerequisites

- Windows OS
- Python 3.11 or newer
- [FEBio Studio](https://febio.org/) (FEBio4 solver installed and in PATH)

#### Setup

```powershell
git clone https://github.com/A6721jpn/vexis.git
cd vexis

python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

#### Run the GUI

1.  Start the application:
    ```powershell
    python gui_main.py
    ```
2.  Place your CAD file (`.stp`) in the `input/` folder. It will appear in the job list automatically.
3.  Click **Start Batch** to begin analysis.
4.  Once complete, select the job to view the **Force-Stroke Graph** and **3D Results**.

#### Run the CLI

For headless automation:
```powershell
python main.py
```

### Option B: Run a Packaged App

Use this route when you have a packaged VEXIS distribution such as
`VEXIS-CAE.exe`. The package includes Python runtime components, so users do not
need to install Python or project dependencies separately.

1.  Download or receive the packaged `VEXIS-CAE` distribution.
2.  Extract it to a writable folder.
3.  Launch `VEXIS-CAE.exe`.
4.  Place `.stp` or `.step` files in the packaged `input/` folder and run the workflow from the GUI.

## Documentation

For more detailed information, please refer to the following documents:

- [Workflow Guide (JA)](doc/workflow_guide_ja.md): Installation, data prep, and GUI reference.
- [Release Notes](doc/release_notes.md): Version history and changes.




---
*Vexis is currently optimized for rubber keycap buckling analysis.*

Copyright (c) 2024-2026 A.O.

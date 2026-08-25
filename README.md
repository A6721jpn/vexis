# VEXIS CAE
![VEXIS CAE Logo](doc/VEXIS-CAE-LOGO-LARGE_black.png)

VEXIS CAE is a specialized FEA workflow for rubber dome buckling analysis. It streamlines the entire process from STEP input to FEBio execution and force-stroke result review, making iterative evaluation faster and more repeatable.

## Demo Video

[![Watch the demo video on YouTube](https://img.youtube.com/vi/vNZM0MbpSeE/hqdefault.jpg)](https://www.youtube.com/watch?v=vNZM0MbpSeE)

## Quick Start

### Requirements

- Windows
- FEBio Studio / `febio4.exe`
- Python environment with `requirements.txt`, or the packaged `VEXIS-CAE.exe`

If FEBio is not available in `PATH`, set `analysis.febio_path` in `config/config.yaml`.

### Run from GUI

```bash
pip install -r requirements.txt
python gui_main.py
```

Or launch the packaged `VEXIS-CAE.exe`.

### Run from CLI

```bash
python main.py
python main.py --mesh-only
python main.py --skip-mesh
```

### Basic Flow

1. Place `.stp` or `.step` files in `input/`.
2. Run the job from the GUI or CLI.
3. Review graphs, CSV data, and logs in `results/`.

## Main Folders

- `input/`: STEP input files
- `temp/`: generated mesh and intermediate FEBio files
- `results/`: graphs, CSV data, and logs
- `config/config.yaml`: solver path and analysis settings

## Documentation

- [Workflow Guide (JA)](doc/workflow_guide_ja.md)
- [Release Notes](doc/release_notes.md)

## License

Licensed under the [GNU GPL v3](LICENSE).

Copyright (c) 2024-2026 A.O.

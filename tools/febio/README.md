# FEBio Source Build For VEXIS

This folder holds a repo-local FEBio build workflow for VEXIS on Windows.

The goal is to build a FEBio solver with MKL enabled without modifying the
global PATH or installing project-specific binaries into system locations.

## What the script does

`Build-FEBio.ps1` performs the following steps:

1. Finds a local Visual Studio Build Tools installation.
2. Downloads `nuget.exe` into this folder if it is missing.
3. Installs Intel oneMKL development and runtime packages into
   `tools/febio/packages/nuget`.
4. Creates a small compatibility library directory so FEBio's CMake files can
   consume the NuGet MKL import libraries.
5. Clones or refreshes the FEBio source tree at the requested tag.
6. Configures FEBio in a VEXIS-oriented profile:
   `USE_MKL=ON`, `USE_FFTW=OFF`, `USE_HYPRE=OFF`, `USE_LEVMAR=OFF`,
   `USE_MMG=OFF`, `USE_ZLIB=OFF`, `USE_PDL=OFF`, `USE_SUPERLU_MT=OFF`.
7. Builds FEBio with Ninja.
8. Copies the required MKL/OpenMP/TBB runtime DLLs into the FEBio `bin`
   directory so `febio4.exe` can run as a self-contained local solver.

The current profile is intentionally minimal because VEXIS currently uses the
solid solver, Ogden-based uncoupled viscoelastic material, rigid body motion,
and `sliding-elastic` contact. Those features only require a working FEBio
solver with MKL-backed Pardiso. Optional FEBio features that depend on FFTW,
HYPRE, LEVMAR, MMG, or zlib are left disabled in this profile.

## Tested versions

This setup was validated in this repository on 2026-04-22 with:

- FEBio tag `v4.12`
- Intel oneMKL NuGet package `intelmkl.devel.win-x64` `2025.3.1.9`
- Intel OpenMP NuGet dependency `2025.3.0.640`
- Visual Studio Build Tools 2022

## Build command

Run from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\febio\Build-FEBio.ps1
```

If you want to force a clean rebuild:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\febio\Build-FEBio.ps1 -CleanBuild
```

If you want to refresh the FEBio source checkout to the pinned tag:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\febio\Build-FEBio.ps1 -RefreshSource
```

## Output paths

After a successful build, the solver will be available at:

```text
tools/febio/build/4.12-vexis/bin/febio4.exe
```

The generated `febio.xml` lives next to the executable in the same `bin`
directory.

## Connecting it to VEXIS

VEXIS already supports relative `analysis.febio_path` values. Set the
following in `config/config.yaml`:

```yaml
analysis:
  febio_path: "tools/febio/build/4.12-vexis/bin/febio4.exe"
```

`analysis_helpers.py` now adds `-config <solver-dir>/febio.xml` automatically
when a sibling config file exists, so the built solver will use the MKL-backed
`pardiso` default solver from its local config file.

## Local-only artifacts

The following paths are intentionally ignored by Git:

- `tools/febio/source/`
- `tools/febio/build/`
- `tools/febio/packages/`
- `tools/febio/nuget.exe`
- `tools/deps/vcpkg/`

That keeps the repository clean while still allowing a full local source build.

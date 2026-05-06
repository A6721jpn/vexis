# Bundled FEBio Solver

Place the platform-specific FEBio solver in this directory:

- macOS/Linux: `solver/febio4`
- Windows: `solver/febio4.exe`

For the local Apple Silicon build, FEBio shared libraries live in `solver/lib/`
and the executable rpath is set to `@executable_path/lib`.

The local binary is intentionally ignored by Git. Rebuild it from:

```bash
git clone --depth 1 --branch febio4 https://github.com/febiosoftware/FEBio /private/tmp/FEBio-febio4
cmake -S /private/tmp/FEBio-febio4 -B /private/tmp/FEBio-febio4/cbuild -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_OSX_ARCHITECTURES=arm64 \
  -DUSE_MKL=OFF \
  -DUSE_HYPRE=OFF \
  -DUSE_SUPERLU_MT=OFF \
  -DUSE_MMG=OFF \
  -DUSE_LEVMAR=OFF \
  -DUSE_PDL=OFF
cmake --build /private/tmp/FEBio-febio4/cbuild --target febio4 --config Release --parallel 8
```

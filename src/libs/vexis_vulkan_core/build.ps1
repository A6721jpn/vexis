# vexis_vulkan_core build script

Write-Host "Building vexis_vulkan_core with maturin..."
# --release is used for production mode for fast performance
maturin build --release

if ($LASTEXITCODE -eq 0) {
    Write-Host "Build success! To install into the active environment, run:" -ForegroundColor Green
    Write-Host "maturin develop --release" -ForegroundColor Cyan
} else {
    Write-Host "Build failed. Please ensure Rust and maturin are installed." -ForegroundColor Red
}

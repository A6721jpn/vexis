[CmdletBinding()]
param(
    [string]$FebioVersion = "v4.12",
    [switch]$RefreshSource,
    [switch]$CleanBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot "..\.."))

$sourceDir = Join-Path $scriptRoot "source"
$buildDir = Join-Path $scriptRoot ("build\" + ($FebioVersion.TrimStart("v") + "-vexis"))
$packagesRoot = Join-Path $scriptRoot "packages"
$nugetRoot = Join-Path $packagesRoot "nuget"
$nugetExe = Join-Path $scriptRoot "nuget.exe"
$mklCompatLibDir = Join-Path $packagesRoot "mkl-compat\lib"

$mklPackageId = "intelmkl.devel.win-x64"
$mklVersion = "2025.3.1.9"
$openMpPackageId = "intelopenmp.devel.win"
$openMpVersion = "2025.3.0.640"
$mklRedistId = "intelmkl.redist.win-x64"
$tbbRedistId = "inteltbb.redist.win"
$tbbRedistVersion = "2022.3.0.380"

$mklPackageDir = Join-Path $nugetRoot "$mklPackageId.$mklVersion"
$openMpPackageDir = Join-Path $nugetRoot "$openMpPackageId.$openMpVersion"
$mklRedistDir = Join-Path $nugetRoot "$mklRedistId.$mklVersion"
$openMpRedistDir = Join-Path $nugetRoot "intelopenmp.redist.win.$openMpVersion"
$tbbRedistDir = Join-Path $nugetRoot "$tbbRedistId.$tbbRedistVersion"

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message"
}

function Get-VsBuildTools {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) {
        throw "vswhere.exe was not found. Install Visual Studio Build Tools first."
    }

    $instances = & $vswhere -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -format json | ConvertFrom-Json
    if (-not $instances) {
        throw "No Visual Studio C++ Build Tools installation was found."
    }

    $preferred = $instances | Where-Object { $_.installationPath -like "*\2022\BuildTools" } | Select-Object -First 1
    if (-not $preferred) {
        $preferred = $instances | Sort-Object installationVersion -Descending | Select-Object -First 1
    }

    $vcvars = Join-Path $preferred.installationPath "VC\Auxiliary\Build\vcvars64.bat"
    $cmake = Join-Path $preferred.installationPath "Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"

    if (-not (Test-Path $vcvars)) {
        throw "vcvars64.bat was not found under $($preferred.installationPath)"
    }
    if (-not (Test-Path $cmake)) {
        throw "cmake.exe was not found under $($preferred.installationPath)"
    }

    return @{
        InstallationPath = $preferred.installationPath
        VcVars = $vcvars
        CMake = $cmake
    }
}

function Ensure-NuGet {
    if (Test-Path $nugetExe) {
        return
    }

    Write-Step "Downloading nuget.exe"
    New-Item -ItemType Directory -Force $scriptRoot | Out-Null
    & curl.exe -L "https://dist.nuget.org/win-x86-commandline/latest/nuget.exe" -o $nugetExe
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $nugetExe)) {
        throw "Failed to download nuget.exe"
    }
}

function Install-NuGetPackage {
    param(
        [Parameter(Mandatory = $true)][string]$PackageId,
        [Parameter(Mandatory = $true)][string]$Version
    )

    $targetDir = Join-Path $nugetRoot "$PackageId.$Version"
    if (Test-Path $targetDir) {
        return
    }

    Write-Step "Installing $PackageId $Version"
    New-Item -ItemType Directory -Force $nugetRoot | Out-Null
    & $nugetExe install $PackageId -Version $Version -OutputDirectory $nugetRoot -NonInteractive -DirectDownload | Out-Host
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $targetDir)) {
        throw "Failed to install NuGet package $PackageId $Version"
    }
}

function Ensure-FEBioSource {
    if ($RefreshSource -and (Test-Path $sourceDir)) {
        Write-Step "Refreshing FEBio source checkout"
        Remove-Item -LiteralPath $sourceDir -Recurse -Force
    }

    if (-not (Test-Path (Join-Path $sourceDir ".git"))) {
        Write-Step "Cloning FEBio $FebioVersion"
        & git clone --depth 1 --branch $FebioVersion https://github.com/febiosoftware/FEBio.git $sourceDir | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to clone FEBio source"
        }
        return
    }

    Write-Step "Checking out FEBio $FebioVersion"
    Push-Location $sourceDir
    try {
        & git fetch --tags --force --depth 1 origin $FebioVersion | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to fetch FEBio tag $FebioVersion"
        }

        & git checkout --force $FebioVersion | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to checkout FEBio tag $FebioVersion"
        }
    }
    finally {
        Pop-Location
    }
}

function New-MklCompatLibs {
    $srcLibDir = Join-Path $mklPackageDir "build\native\win-x64"
    $compatMap = @{
        "mkl_intel_lp64.lib" = "mkl_intel_lp64_dll.lib"
        "mkl_core.lib" = "mkl_core_dll.lib"
        "mkl_intel_thread.lib" = "mkl_intel_thread_dll.lib"
    }

    New-Item -ItemType Directory -Force $mklCompatLibDir | Out-Null

    foreach ($pair in $compatMap.GetEnumerator()) {
        $source = Join-Path $srcLibDir $pair.Value
        $dest = Join-Path $mklCompatLibDir $pair.Key
        if (-not (Test-Path $source)) {
            throw "Required MKL import library was not found: $source"
        }
        Copy-Item -LiteralPath $source -Destination $dest -Force
    }
}

function Invoke-InVSToolchain {
    param(
        [Parameter(Mandatory = $true)][string[]]$Commands,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$VcVarsPath
    )

    New-Item -ItemType Directory -Force $WorkingDirectory | Out-Null
    $cmdPath = Join-Path $WorkingDirectory "codex-febio-build.cmd"

    $lines = @(
        "@echo off",
        "setlocal",
        "call `"$VcVarsPath`" >nul",
        "if errorlevel 1 exit /b %errorlevel%"
    ) + $Commands + @(
        "exit /b %errorlevel%"
    )

    Set-Content -LiteralPath $cmdPath -Value $lines -Encoding ascii
    & cmd.exe /d /c $cmdPath
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed inside Visual Studio toolchain environment."
    }
}

function Stage-RuntimeDlls {
    param([Parameter(Mandatory = $true)][string]$BinDir)

    $patterns = @(
        (Join-Path $mklRedistDir "runtimes\win-x64\native\*.dll"),
        (Join-Path $openMpRedistDir "runtimes\win-x64\native\libiomp5md.dll"),
        (Join-Path $tbbRedistDir "runtimes\win-x64\native\*.dll")
    )

    foreach ($pattern in $patterns) {
        Copy-Item $pattern $BinDir -Force
    }
}

Write-Step "Resolving Visual Studio build environment"
$vs = Get-VsBuildTools

Write-Step "Ensuring FEBio source tree"
Ensure-FEBioSource

Write-Step "Ensuring local NuGet tooling and MKL packages"
Ensure-NuGet
Install-NuGetPackage -PackageId $mklPackageId -Version $mklVersion
New-MklCompatLibs

if ($CleanBuild -and (Test-Path $buildDir)) {
    Write-Step "Cleaning previous build directory"
    Remove-Item -LiteralPath $buildDir -Recurse -Force
}

New-Item -ItemType Directory -Force $buildDir | Out-Null

$mklInc = Join-Path $mklPackageDir "build\native\include"
$ompLib = Join-Path $openMpPackageDir "build\native\win-x64\libiomp5md.lib"

if (-not (Test-Path $mklInc)) {
    throw "MKL include directory was not found: $mklInc"
}
if (-not (Test-Path $ompLib)) {
    throw "OpenMP import library was not found: $ompLib"
}

Write-Step "Configuring FEBio $FebioVersion"
$configureCommand = @(
    "`"$($vs.CMake)`" -S `"$sourceDir`" -B `"$buildDir`" -G Ninja " +
    "-DCMAKE_BUILD_TYPE=Release " +
    "-DMKL_INC=`"$mklInc`" " +
    "-DMKL_LIB_DIR=`"$mklCompatLibDir`" " +
    "-DMKL_OMP_LIB=`"$ompLib`" " +
    "-DUSE_MKL=ON " +
    "-DUSE_FFTW=OFF " +
    "-DUSE_HYPRE=OFF " +
    "-DUSE_LEVMAR=OFF " +
    "-DUSE_MMG=OFF " +
    "-DUSE_ZLIB=OFF " +
    "-DUSE_PDL=OFF " +
    "-DUSE_SUPERLU_MT=OFF"
)
Invoke-InVSToolchain -Commands $configureCommand -WorkingDirectory $buildDir -VcVarsPath $vs.VcVars

Write-Step "Building FEBio $FebioVersion"
$buildCommand = @(
    "`"$($vs.CMake)`" --build `"$buildDir`" --parallel"
)
Invoke-InVSToolchain -Commands $buildCommand -WorkingDirectory $buildDir -VcVarsPath $vs.VcVars

$binDir = Join-Path $buildDir "bin"
if (-not (Test-Path (Join-Path $binDir "febio4.exe"))) {
    throw "Build completed without generating febio4.exe"
}

Write-Step "Staging MKL runtime DLLs into $binDir"
Stage-RuntimeDlls -BinDir $binDir

Write-Host ""
Write-Host "FEBio build completed."
Write-Host "  FEBio source  : $sourceDir"
Write-Host "  Build output  : $buildDir"
Write-Host "  Solver binary : $(Join-Path $binDir 'febio4.exe')"
Write-Host ""
Write-Host "To use this solver from VEXIS, set analysis.febio_path in config/config.yaml to:"
Write-Host "  tools/febio/build/$($FebioVersion.TrimStart('v'))-vexis/bin/febio4.exe"

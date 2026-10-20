param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^\d+\.\d+\.\d+([-.+][0-9A-Za-z.-]+)?$")]
    [string]$Version
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$IconUrl = "https://raw.githubusercontent.com/wtffidy/shit-yourself/main/SkuaIcon.ico"
$IconPath = Join-Path $Root "SkuaIcon.ico"
$BuildRoot = Join-Path $Root "build-velopack"
$DistRoot = Join-Path $BuildRoot "dist"
$PackageDir = Join-Path $BuildRoot "package"
$ReleasesDir = Join-Path $Root "Releases"

if (-not (Test-Path $IconPath)) {
    Write-Host "Downloading application icon..."
    Invoke-WebRequest -Uri $IconUrl -OutFile $IconPath
}

Write-Host "Installing/updating PyInstaller..."
python -m pip install --upgrade pyinstaller
if ($LASTEXITCODE -ne 0) { throw "PyInstaller installation failed." }

$Vpk = Join-Path $env:USERPROFILE ".dotnet\tools\vpk.exe"
if (-not (Test-Path $Vpk)) {
    Write-Host "Installing Velopack CLI..."
    dotnet tool install --global vpk
    if ($LASTEXITCODE -ne 0) { throw "Velopack CLI installation failed. Ensure the .NET SDK is installed." }
}
if (-not (Test-Path $Vpk)) {
    throw "Could not find vpk.exe at $Vpk. Restart the terminal and try again."
}

if (Test-Path $BuildRoot) { Remove-Item $BuildRoot -Recurse -Force }
New-Item -ItemType Directory -Path $DistRoot, $PackageDir -Force | Out-Null

Write-Host "Building SkuaManager..."
python -m PyInstaller --noconfirm --clean --onedir --contents-directory manager_internal --name SkuaManager --distpath $DistRoot --workpath (Join-Path $BuildRoot "work-manager") --specpath (Join-Path $BuildRoot "spec-manager") --windowed --icon $IconPath --add-data "$IconPath;." dashboard_gui.py
if ($LASTEXITCODE -ne 0) { throw "SkuaManager build failed." }

Write-Host "Building SkuaRelay..."
python -m PyInstaller --noconfirm --clean --onedir --contents-directory relay_internal --name SkuaRelay --distpath $DistRoot --workpath (Join-Path $BuildRoot "work-relay") --specpath (Join-Path $BuildRoot "spec-relay") --console --icon $IconPath --add-data "$IconPath;." --add-data "index.html;." relay.py
if ($LASTEXITCODE -ne 0) { throw "SkuaRelay build failed." }

Copy-Item (Join-Path $DistRoot "SkuaManager\SkuaManager.exe") $PackageDir
Copy-Item (Join-Path $DistRoot "SkuaManager\manager_internal") $PackageDir -Recurse
Copy-Item (Join-Path $DistRoot "SkuaRelay\SkuaRelay.exe") $PackageDir
Copy-Item (Join-Path $DistRoot "SkuaRelay\relay_internal") $PackageDir -Recurse

Write-Host "Packing Velopack release v$Version..."
& $Vpk pack --packId SkuaDashboard --packVersion $Version --packDir $PackageDir --mainExe SkuaManager.exe --packTitle "Skua Dashboard" --packAuthors "wtffidy" --icon $IconPath --outputDir $ReleasesDir
if ($LASTEXITCODE -ne 0) { throw "Velopack packaging failed." }

Write-Host ""
Write-Host "Velopack package created successfully."
Write-Host "Version: $Version"
Write-Host "Output: $ReleasesDir"
Write-Host "Test the generated Setup.exe before publishing a release."

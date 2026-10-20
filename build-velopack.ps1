param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^\d+\.\d+\.\d+([+-][0-9A-Za-z.-]+)?$")]
    [string]$Version,

    [switch]$UpdateTools
)

$ErrorActionPreference = "Stop"
# Merge native stderr into stdout so Windows PowerShell 5.1 and PowerShell 7 can safely inspect exit codes.
$PSNativeCommandUseErrorActionPreference = $false
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Test-Path (Join-Path $Root "requirements-build.txt"))) {
    throw "Build dependency file not found: $(Join-Path $Root 'requirements-build.txt')"
}

Write-Host "Checking and installing required Python build packages..."
$PipOutput = & python -m pip install -r (Join-Path $Root "requirements-build.txt") 2>&1
$PipExitCode = $LASTEXITCODE
$PipOutput | ForEach-Object { Write-Host $_ }
if ($PipExitCode -ne 0) { throw "Python build dependency installation failed. Ensure Python and pip are installed and available on PATH." }

if ($UpdateTools) {
    Write-Host "Updating PyInstaller and Pillow..."
    $UpdateOutput = & python -m pip install --upgrade pyinstaller Pillow 2>&1
    $UpdateExitCode = $LASTEXITCODE
    $UpdateOutput | ForEach-Object { Write-Host $_ }
    if ($UpdateExitCode -ne 0) { throw "Python build tool update failed." }
}

$IconUrl = "https://raw.githubusercontent.com/wtffidy/shit-yourself/main/SkuaIcon.ico"
$IconPath = Join-Path $Root "SkuaIcon.ico"
$IndexPath = Join-Path $Root "index.html"
$BuildRoot = Join-Path $Root "build-velopack"
$DistRoot = Join-Path $BuildRoot "dist"
$PackageDir = Join-Path $BuildRoot "package"
$ReleasesDir = Join-Path $Root "Releases"

if (-not (Test-Path $IconPath)) {
    Write-Host "Downloading application icon..."
    Invoke-WebRequest -Uri $IconUrl -OutFile $IconPath
}

if (-not (Test-Path $IndexPath)) {
    throw "Dashboard file not found: $IndexPath"
}


$Vpk = Join-Path $env:USERPROFILE ".dotnet\tools\vpk.exe"
if (-not (Test-Path $Vpk)) {
    Write-Host "Installing Velopack CLI..."
    dotnet tool install --global vpk
    if ($LASTEXITCODE -ne 0) { throw "Velopack CLI installation failed. Ensure the .NET SDK is installed." }
}
if (-not (Test-Path $Vpk)) {
    throw "Could not find vpk.exe at $Vpk. Restart the terminal and try again."
}

# Clear final outputs and spec files, but retain PyInstaller work caches for faster repeat builds.
foreach ($Path in @(
    $DistRoot,
    $PackageDir,
    (Join-Path $BuildRoot "spec-manager"),
    (Join-Path $BuildRoot "spec-relay")
)) {
    if (Test-Path $Path) { Remove-Item $Path -Recurse -Force }
}
New-Item -ItemType Directory -Path $DistRoot, $PackageDir,
    (Join-Path $BuildRoot "work-manager"),
    (Join-Path $BuildRoot "work-relay"),
    (Join-Path $BuildRoot "spec-manager"),
    (Join-Path $BuildRoot "spec-relay") -Force | Out-Null

Write-Host "Building SkuaManager and SkuaRelay in parallel..."
$ManagerJob = Start-Job -Name "Build-SkuaManager" -ArgumentList $Root, $IconPath, $BuildRoot, $DistRoot -ScriptBlock {
    param($Root, $IconPath, $BuildRoot, $DistRoot)
    Set-Location $Root
    $PSNativeCommandUseErrorActionPreference = $false
    $PyInstallerArgs = @(
        "-m", "PyInstaller", "--noconfirm", "--onedir", "--contents-directory", "manager_internal",
        "--name", "SkuaManager", "--distpath", $DistRoot,
        "--workpath", (Join-Path $BuildRoot "work-manager"),
        "--specpath", (Join-Path $BuildRoot "spec-manager"),
        "--windowed", "--icon", $IconPath,
        "--add-data", "$IconPath;.",
        (Join-Path $Root "dashboard_gui.py")
    )
    & python @PyInstallerArgs 2>&1
    if ($LASTEXITCODE -ne 0) { throw "SkuaManager build failed with exit code $LASTEXITCODE." }
}

$RelayJob = Start-Job -Name "Build-SkuaRelay" -ArgumentList $Root, $IconPath, $IndexPath, $BuildRoot, $DistRoot -ScriptBlock {
    param($Root, $IconPath, $IndexPath, $BuildRoot, $DistRoot)
    Set-Location $Root
    $PyInstallerArgs = @(
        "-m", "PyInstaller", "--noconfirm", "--onedir", "--contents-directory", "relay_internal",
        "--name", "SkuaRelay", "--distpath", $DistRoot,
        "--workpath", (Join-Path $BuildRoot "work-relay"),
        "--specpath", (Join-Path $BuildRoot "spec-relay"),
        "--console", "--icon", $IconPath,
        "--add-data", "$IconPath;.",
        "--add-data", "$IndexPath;.",
        (Join-Path $Root "relay.py")
    )
    & python @PyInstallerArgs 2>&1
    if ($LASTEXITCODE -ne 0) { throw "SkuaRelay build failed with exit code $LASTEXITCODE." }
}

$Jobs = @($ManagerJob, $RelayJob)
$Jobs | Wait-Job | Out-Null
$Jobs | ForEach-Object {
    Write-Host ""
    Write-Host "===== $($_.Name) output ====="
    Receive-Job -Job $_
}
$FailedJobs = @($Jobs | Where-Object { $_.State -ne "Completed" })
$Jobs | Remove-Job -Force

if ($FailedJobs.Count -gt 0) {
    throw "One or more PyInstaller builds failed. See the output above."
}

Copy-Item (Join-Path $DistRoot "SkuaManager\SkuaManager.exe") $PackageDir
Copy-Item (Join-Path $DistRoot "SkuaManager\manager_internal") $PackageDir -Recurse
Copy-Item (Join-Path $DistRoot "SkuaRelay\SkuaRelay.exe") $PackageDir
Copy-Item (Join-Path $DistRoot "SkuaRelay\relay_internal") $PackageDir -Recurse

# Remove previous installers and release metadata so rebuilding the same version does not collide with old output.
if (Test-Path $ReleasesDir) {
    Write-Host "Cleaning previous release files..."
    Get-ChildItem -LiteralPath $ReleasesDir -Force | Remove-Item -Recurse -Force
}
else {
    New-Item -ItemType Directory -Path $ReleasesDir -Force | Out-Null
}

Write-Host "Packing Velopack release v$Version..."
& $Vpk pack --packId SkuaDashboard --packVersion $Version --packDir $PackageDir --mainExe SkuaManager.exe --packTitle "Skua Dashboard" --packAuthors "wtffidy" --icon $IconPath --outputDir $ReleasesDir
if ($LASTEXITCODE -ne 0) { throw "Velopack packaging failed." }

Write-Host ""
Write-Host "Velopack package created successfully."
Write-Host "Version: $Version"
Write-Host "Output: $ReleasesDir"
Write-Host "Test the generated Setup.exe before publishing a release."

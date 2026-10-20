param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^\d+\.\d+\.\d+([-.+][0-9A-Za-z.-]+)?$")]
    [string]$Version,

    [switch]$UpdateTools
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

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

if ($UpdateTools) {
    Write-Host "Updating PyInstaller..."
    python -m pip install --upgrade pyinstaller
}
else {
    Write-Host "Checking PyInstaller..."
    python -m pip install pyinstaller
}
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

Write-Host "Building SkuaManager and SkuaRelay in parallel..."
$ManagerJob = Start-Job -Name "Build-SkuaManager" -ArgumentList $Root, $IconPath, $BuildRoot, $DistRoot -ScriptBlock {
    param($Root, $IconPath, $BuildRoot, $DistRoot)
    Set-Location $Root
    $Args = @(
        "-m", "PyInstaller", "--noconfirm", "--onedir", "--contents-directory", "manager_internal",
        "--name", "SkuaManager", "--distpath", $DistRoot,
        "--workpath", (Join-Path $BuildRoot "work-manager"),
        "--specpath", (Join-Path $BuildRoot "spec-manager"),
        "--windowed", "--icon", $IconPath,
        "--add-data", "$IconPath;.",
        (Join-Path $Root "dashboard_gui.py")
    )
    & python @Args
    if ($LASTEXITCODE -ne 0) { throw "SkuaManager build failed with exit code $LASTEXITCODE." }
}

$RelayJob = Start-Job -Name "Build-SkuaRelay" -ArgumentList $Root, $IconPath, $IndexPath, $BuildRoot, $DistRoot -ScriptBlock {
    param($Root, $IconPath, $IndexPath, $BuildRoot, $DistRoot)
    Set-Location $Root
    $Args = @(
        "-m", "PyInstaller", "--noconfirm", "--onedir", "--contents-directory", "relay_internal",
        "--name", "SkuaRelay", "--distpath", $DistRoot,
        "--workpath", (Join-Path $BuildRoot "work-relay"),
        "--specpath", (Join-Path $BuildRoot "spec-relay"),
        "--console", "--icon", $IconPath,
        "--add-data", "$IconPath;.",
        "--add-data", "$IndexPath;.",
        (Join-Path $Root "relay.py")
    )
    & python @Args
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

Write-Host "Packing Velopack release v$Version..."
& $Vpk pack --packId SkuaDashboard --packVersion $Version --packDir $PackageDir --mainExe SkuaManager.exe --packTitle "Skua Dashboard" --packAuthors "wtffidy" --icon $IconPath --outputDir $ReleasesDir
if ($LASTEXITCODE -ne 0) { throw "Velopack packaging failed." }

Write-Host ""
Write-Host "Velopack package created successfully."
Write-Host "Version: $Version"
Write-Host "Output: $ReleasesDir"
Write-Host "Test the generated Setup.exe before publishing a release."

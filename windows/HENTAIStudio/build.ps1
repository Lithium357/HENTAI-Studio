param(
    [switch]$Install,
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path (Split-Path $sourceRoot -Parent) -Parent
$publishRoot = Join-Path $projectRoot 'dist\HENTAIStudio'
$env:DOTNET_CLI_HOME = Join-Path $projectRoot '.dotnet-home'
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'

dotnet publish (Join-Path $sourceRoot 'HENTAIStudio.csproj') `
    --configuration Release --runtime win-x64 --self-contained false `
    --output $publishRoot -p:PublishSingleFile=true `
    -p:IncludeNativeLibrariesForSelfExtract=true -p:DebugType=None -p:DebugSymbols=false
if ($LASTEXITCODE -ne 0) { throw "dotnet publish exited with code $LASTEXITCODE" }
if (-not $Install) {
    Write-Output (Join-Path $publishRoot 'HENTAI Studio.exe')
    return
}

# Installation is explicit and does not delete existing app or workspace data.
$installRoot = Join-Path $env:LOCALAPPDATA 'Programs\HENTAI Studio'
New-Item -ItemType Directory -Force -Path $installRoot | Out-Null
Copy-Item -Path (Join-Path $publishRoot '*') -Destination $installRoot -Recurse -Force
$backendRoot = Join-Path $installRoot 'backend'
& $Python -m venv $backendRoot
if ($LASTEXITCODE -ne 0) { throw 'Failed to create the Studio backend environment.' }
& (Join-Path $backendRoot 'Scripts\python.exe') -m pip install --upgrade $projectRoot
if ($LASTEXITCODE -ne 0) { throw 'Failed to install the Studio backend.' }
$executable = Join-Path $installRoot 'HENTAI Studio.exe'
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) {
    $shortcut = $shell.CreateShortcut((Join-Path $folder 'HENTAI Studio.lnk'))
    $shortcut.TargetPath = $executable
    $shortcut.WorkingDirectory = $installRoot
    $shortcut.IconLocation = "$executable,0"
    $shortcut.Description = 'Standalone training project manager'
    $shortcut.Save()
}
Write-Output $executable

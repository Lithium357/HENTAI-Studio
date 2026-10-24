$ErrorActionPreference = 'Stop'

$sourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path (Split-Path $sourceRoot -Parent) -Parent
$publishRoot = Join-Path $projectRoot 'dist\HENTAIStudio'
$installRoot = Join-Path $env:LOCALAPPDATA 'Programs\HENTAI Studio'
$executable = Join-Path $installRoot 'HENTAI Studio.exe'
$env:DOTNET_CLI_HOME = Join-Path $env:LOCALAPPDATA 'HENTAI Studio\dotnet'
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'

if (Test-Path -LiteralPath $publishRoot) {
    Remove-Item -LiteralPath $publishRoot -Recurse -Force
}

dotnet publish (Join-Path $sourceRoot 'HENTAIStudio.csproj') `
    --configuration Release `
    --runtime win-x64 `
    --self-contained false `
    --output $publishRoot `
    -p:PublishSingleFile=true `
    -p:IncludeNativeLibrariesForSelfExtract=true `
    -p:DebugType=None `
    -p:DebugSymbols=false
if ($LASTEXITCODE -ne 0) { throw "dotnet publish exited with code $LASTEXITCODE" }

if (Test-Path -LiteralPath $installRoot) {
    Remove-Item -LiteralPath $installRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $installRoot | Out-Null
Copy-Item -Path (Join-Path $publishRoot '*') -Destination $installRoot -Recurse -Force

if (-not (Test-Path -LiteralPath $executable)) { throw "Installed executable was not created: $executable" }

$shell = New-Object -ComObject WScript.Shell
$shortcutLocations = @(
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'HENTAI Studio.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'HENTAI Studio.lnk')
)
foreach ($shortcutPath in $shortcutLocations) {
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $executable
    $shortcut.WorkingDirectory = $publishRoot
    $shortcut.IconLocation = "$executable,0"
    $shortcut.Description = 'HENTAI Studio native training control room'
    $shortcut.Save()
}

Write-Output $executable

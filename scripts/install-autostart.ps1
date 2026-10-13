param([switch]$Remove)

$ErrorActionPreference = 'Stop'
$startupFolder = [Environment]::GetFolderPath('Startup')
$destination = Join-Path $startupFolder 'VoiceHold.vbs'

if ($Remove) {
    if (Test-Path -LiteralPath $destination) {
        Remove-Item -LiteralPath $destination
    }
    [Environment]::SetEnvironmentVariable('VoiceHoldPython', $null, 'User')
    [Environment]::SetEnvironmentVariable('VoiceHoldScript', $null, 'User')
    Write-Output 'VoiceHold auto-start disabled. The running instance is not stopped.'
    return
}

$projectDir = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectDir '.venv\Scripts\pythonw.exe'
$scriptPath = Join-Path $projectDir 'voice_type.py'
foreach ($requiredPath in @($pythonPath, $scriptPath, (Join-Path $projectDir 'voice_config.json'))) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required file missing: $requiredPath. Complete the Quick start steps first."
    }
}

[Environment]::SetEnvironmentVariable('VoiceHoldPython', $pythonPath, 'User')
[Environment]::SetEnvironmentVariable('VoiceHoldScript', $scriptPath, 'User')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'voicehold-startup.vbs') -Destination $destination -Force
Write-Output 'VoiceHold auto-start enabled for the current Windows user. It will start at the next sign-in.'

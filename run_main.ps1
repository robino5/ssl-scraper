$ErrorActionPreference = "Stop"

$projectDirectory = $PSScriptRoot
$mainScript = Join-Path $projectDirectory "main.py"
$requirementsFile = Join-Path $projectDirectory "requirements.txt"
$pythonExecutable = "C:\Program Files\Python313\python.exe"

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        Write-Error "Python was not found. Install Python or update run_main.ps1 with its path."
        exit 1
    }

    $pythonExecutable = $pythonCommand.Source
}

Set-Location -LiteralPath $projectDirectory
Write-Host "Using Python: $pythonExecutable"

$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $pythonExecutable -c "import selenium, pyodbc, PIL, torch, transformers, sentencepiece" 2>$null
$dependencyCheckExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference

if ($dependencyCheckExitCode -ne 0) {
    if (-not (Test-Path -LiteralPath $requirementsFile)) {
        Write-Error "Missing requirements.txt. Copy it beside run_main.ps1."
        exit 1
    }

    Write-Host "Installing required Python packages..."
    $ErrorActionPreference = "Continue"
    & $pythonExecutable -m pip install --user -r $requirementsFile
    $installExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    if ($installExitCode -ne 0) {
        Write-Error "Dependency installation failed. Check Python/pip access and network connectivity."
        exit 1
    }
}

$ErrorActionPreference = "Continue"
& $pythonExecutable $mainScript
$mainExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
exit $mainExitCode
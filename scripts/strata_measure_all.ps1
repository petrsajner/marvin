# Strata measurement sequence (docs/design/2026-10-06-strata-qualification-plan.md).
# Run from the repository once nothing else uses the GPU. Strata, its data and the
# raw results live on the NVMe system drive (%LOCALAPPDATA%\StrataEval and the
# installed Marvin's runtime\models\strata); the repository keeps the code.
$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"
$py = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$root = Join-Path $env:LOCALAPPDATA "StrataEval"
$log = Join-Path $root "measure-all.log"

function Step($title, [string[]]$arguments) {
    "===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $title" | Tee-Object -FilePath $log -Append
    & $py @arguments 2>&1 | Tee-Object -FilePath $log -Append
    "===== exit $LASTEXITCODE" | Tee-Object -FilePath $log -Append
}

Set-Location (Join-Path $PSScriptRoot "..")
Step "Weights SHA-256" @("scripts\strata_qualify.py", "verify")
Step "Phase 0: IQ3_S 256k" @("scripts\strata_eval.py", "run", "--context", "262144")
Step "Phase 0: IQ3_S 128k" @("scripts\strata_eval.py", "run", "--context", "131072")
Step "Phase 0: report" @("scripts\strata_eval.py", "report")
Step "Qualification matrix" @("scripts\strata_qualify.py", "run", "--verify", "--resume")

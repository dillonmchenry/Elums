<#
.SYNOPSIS
  Idempotent, resumable download of local inference weights (M1, local half).
  Order follows ELUMS_BUILD_SCHEDULE.md's background-jobs calendar: by when
  each artifact is first needed, not by size.

.NOTES
  Run from the repo root. Requires .venv-tools (uv venv .venv-tools --python 3.13)
  with audio-separator[cpu] and huggingface_hub installed, and ffmpeg on PATH
  (see docs/vm-baseline.md for the winget install note — PATH changes need a
  fresh shell to take effect automatically).

  CLI GOTCHA (verified Oct 3 2026, see config/models.yaml): audio-separator's
  model selector is -m/--model_filename, NOT a positional argument. Passing
  the filename positionally silently downloads the DEFAULT model instead and
  exits 0 with no error.
#>

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path "$PSScriptRoot\.."
$modelDir = Join-Path $repoRoot "models"
$venvPython = Join-Path $repoRoot ".venv-tools\Scripts\python.exe"
$venvSeparator = Join-Path $repoRoot ".venv-tools\Scripts\audio-separator.exe"

New-Item -ItemType Directory -Force -Path $modelDir | Out-Null

function Step($name, $targetFile, [scriptblock]$action) {
    $target = Join-Path $modelDir $targetFile
    if (Test-Path $target) {
        Write-Host "[skip] $name -> already present at $target"
        return
    }
    Write-Host "[download] $name -> $target"
    & $action
}

# --- Item 1: Mel-Band RoFormer vocals checkpoint (today, M8) ---
Step "Mel-Band RoFormer vocals (Kimberley Jensen)" "vocals_mel_band_roformer.ckpt" {
    & $venvSeparator -m vocals_mel_band_roformer.ckpt --model_file_dir=$modelDir --download_model_only
}

# --- Item 2: all-in-one-infer checkpoints (first needed Sun Oct 4) ---
# DEFERRED: mechanism confirmed (huggingface_hub.hf_hub_download from
# huggingface.co/taejunkim/allinone, ungated, verified Oct 3 2026), but the
# package has 8 CV folds (harmonix-fold0..7) plus "all-*" and "raveform-*"
# variants and no single canonical default was confirmed today. Resolve the
# fold the package actually loads by default when `allin1` is installed on
# Sun Oct 4, then download just that fold here rather than all 17 files.

# --- Item 3: Whisper large-v3-turbo (first needed Mon Oct 5) ---
Step "Whisper large-v3-turbo" "whisper-large-v3-turbo\config.json" {
    & $venvPython -c "
from huggingface_hub import snapshot_download
snapshot_download('openai/whisper-large-v3-turbo', local_dir=r'$modelDir\whisper-large-v3-turbo')
"
}

# --- Item 4: RMVPE (first needed Tue Oct 6) ---
Step "RMVPE" "rmvpe.pt" {
    & $venvPython -c "
from huggingface_hub import hf_hub_download
import shutil
p = hf_hub_download('lj1995/VoiceConversionWebUI', 'rmvpe.pt')
shutil.copy(p, r'$modelDir\rmvpe.pt')
"
}

# --- Item 5: LAION-CLAP (first needed Tue Oct 6) ---
Step "LAION-CLAP (larger_clap_music_and_speech)" "clap-music-speech\config.json" {
    & $venvPython -c "
from huggingface_hub import snapshot_download
snapshot_download('laion/larger_clap_music_and_speech', local_dir=r'$modelDir\clap-music-speech')
"
}

Write-Host "`nDone. Current models/ contents:"
Get-ChildItem $modelDir -Recurse -File | Select-Object FullName, Length | Format-Table -AutoSize

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
# Resolved Oct 4 2026 (N1, EC-3): the package's default model is the
# `harmonix-all` ENSEMBLE, not a single fold — it loads and averages all 8
# `harmonix-fold0..7` checkpoints (~1.4 MB each, ~11 MB total). Confirmed by
# running `allin1_infer.analyze()` once and reading the actual cache
# contents rather than guessing; see config/models.yaml's
# `structure_beats.harmonix_all` entry for the full file list.
#
# Downloads into the SAME HF_HOME elums/ingest/structure.py points at
# (${MODEL_ROOT}/hf-cache) — not a separate flat layout — so this
# pre-warms exactly the cache the real job reads, rather than staging
# files the library's own resolver would never look at. allow_patterns
# skips the repo's unused "all-*" and "raveform-*" fold variants.
Step "all-in-one-infer harmonix-all (8-fold ensemble)" "hf-cache\hub\models--taejunkim--allinone\refs\main" {
    & $venvPython -c "
import os
os.environ['HF_HOME'] = r'$modelDir\hf-cache'
from huggingface_hub import snapshot_download
snapshot_download(
    'taejunkim/allinone',
    allow_patterns=['harmonix-fold*.pth'],
)
"
}
# Separately, the package runs its OWN HTDemucs separation on the original
# mix (per IMPLEMENTATION_PLAN_2026-10-04.md §3 — it needs 4 demucs stems,
# which Saturday's 2-stem Mel-Band RoFormer output cannot supply). That
# checkpoint (955717e8-8726e21a.th, 80.2 MB) comes from torch.hub, not
# huggingface_hub, and elums/ingest/structure.py pins its cache directory
# via `torch.hub.set_dir()` to ${MODEL_ROOT}/torch-cache at import time —
# verified Oct 4 2026 that a bare TORCH_HOME env var is NOT honored by this
# download path in this package version, so it is set in code instead.
# Nothing to do here; the first real structure job downloads it once.

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

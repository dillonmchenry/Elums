#!/usr/bin/env bash
# VM-side dataset downloads (M1, VM half). Idempotent via `hf download`'s own
# resume behaviour. Run inside tmux â€” never in a foreground ssh session
# (EC-7/EC-8 in the implementation plan).
set -euo pipefail
source /venv/main/bin/activate

echo "=== NanoPitch-PreExtract (3.64 GB, first needed Thu Oct 8) ==="
hf download smulelabs/NanoPitch-PreExtract --repo-type dataset

echo "=== GTSinger (54 GB, first needed Fri Oct 9) ==="
hf download GTSinger/GTSinger --repo-type dataset

echo "=== done ==="
du -sh "${HF_HOME:-/workspace/.hf_home}"
df -h /

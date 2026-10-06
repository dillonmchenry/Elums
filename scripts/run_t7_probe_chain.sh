#!/bin/bash
# T7's probe-then-cache chain, launched detached per the plan's own
# instruction (not a bare tmux session — EC-0's finding on this VM).
set -e
cd /srv/elums

echo "[$(date -u +%FT%TZ)] starting ssl_layer_probe.py (full ~2h stratified subset)"
uv run python3 scripts/ssl_layer_probe.py
echo "[$(date -u +%FT%TZ)] ssl_layer_probe.py done"

echo "[$(date -u +%FT%TZ)] starting cache_ssl_features.py (top 2 layers, full English corpus)"
uv run python3 scripts/cache_ssl_features.py --num-layers 2
echo "[$(date -u +%FT%TZ)] cache_ssl_features.py done"

echo "[$(date -u +%FT%TZ)] T7 chain complete"

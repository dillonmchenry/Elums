"""Entrypoint for the gpu-worker's `python -m procrastinate --app=...`
invocation ONLY.

Importing this module (rather than `elums.jobs.app` directly) is what
registers M8's `separate` task, because this import pulls in
`elums.separation.task`, which imports torch and audio-separator. The
plain `worker` service (the torch-free `app` image) must never import
this module — it keeps using `--app=elums.jobs.app.app` directly. See
docker-compose.yaml's two different `--app=` arguments, and
elums/separation/task.py's module docstring for the full reasoning.
"""

from __future__ import annotations

from elums.jobs.app import app  # noqa: F401  (re-exported for the `--app=` CLI string)
from elums.separation import task  # noqa: F401  (import side effect: registers `separate`)

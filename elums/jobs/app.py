"""Procrastinate app — the queue lives in Postgres, not a separate broker.

The GPU-pinned stages (separation, structure/beats, F0 — see
ELUMS_TECHNICAL_APPROACH.md §11.6) acquire Procrastinate's named lock
`lock="gpu:separation"` so only one GPU-bound task runs at a time across
every worker process, local and VM alike. Tasks are added starting M8;
this module just stands up the connector so `worker` has something to run
and `procrastinate schema --apply` has something to target.
"""

from __future__ import annotations

from procrastinate import App, PsycopgConnector

from elums.config import settings

app = App(connector=PsycopgConnector(conninfo=settings.database_url.replace("+psycopg", "")))

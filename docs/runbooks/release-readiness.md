# Release Readiness Checklist

## Scope
Checklist operativa per dichiarare la piattaforma pronta al primo rollout interno enterprise-core.

## Backend
- `PYTHONPATH=src .venv/bin/python -m pytest -q` verde
- `GET /health/live` risponde `200`
- `GET /health/ready` risponde `200`
- `GET /metrics` espone contatori runtime e lease
- `SDP_CONTROL_PLANE_DSN` configurato correttamente
- migrazioni del control plane eseguite all'avvio

## Workers
- processi worker avviati per:
  - publish
  - extraction
  - artifact publish
  - baseline refresh
- maintenance runner verificati:
  - refresh schedule dispatch
  - artifact retention
  - artifact cleanup
  - stale job recovery
- almeno un job per workflow elaborato con successo su runtime persistente

## Frontend
- `cd frontend/app && npm run test -- --run` verde
- `cd frontend/app && npm run build` verde
- `VITE_API_BASE_URL` configurato
- navigazione shell e pagine principali raggiungibili

## Compose / Deploy
- `docker compose up --build` parte senza errori
- `control-plane-postgres` healthy
- `api` healthy
- `frontend` raggiungibile
- volumi artifact e baseline asset montati

## Recovery / Safety
- lease attive visibili via `GET /metrics`
- `stale_job_recovery` testato su almeno un job orfano
- audit e lineage verificati per publish, extraction e artifact publish

## Remaining non-blocking follow-ups
- heartbeat periodico intra-job per esecuzioni lunghe
- recovery più esplicito di artifact/baseline asset parziali
- SSO/RBAC enterprise
- orchestrazione beyond Compose

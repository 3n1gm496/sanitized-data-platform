# Sanitized Data Platform

Piattaforma interna on-prem per il provisioning self-service di copie sanitizzate e governate dei dati di produzione verso ambienti non-production.

## Obiettivo
Consentire a sviluppatori e tester di ottenere dataset coerenti, mascherati e auditabili per DEV, TEST e COLLAUDO, senza accesso diretto ai dati reali di produzione.

## Stato
Control plane e data plane MVP avanzati, con:
- API applicative Python
- adapter reali PostgreSQL e Oracle
- console web React per self-service, governance e observability

## Avvio locale

### Backend
```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/uvicorn sanitized_data_platform.bootstrap.demo:create_demo_fastapi_app --factory --reload
```

Nota:
- il transport HTTP reale è FastAPI
- `bootstrap.demo` fornisce una composition root locale con dati seed coerenti per UI e API
- `bootstrap.production` carica config centralizzata da environment e abilita health/readiness/metrics
- senza wiring persistente esplicito, `bootstrap.production` richiede `SDP_BOOTSTRAP_MODE=demo` per avvio locale seedato

### Runtime config
Variabili principali:
- `SDP_SERVICE_NAME`
- `SDP_SERVICE_VERSION`
- `SDP_ENVIRONMENT`
- `SDP_BOOTSTRAP_MODE`
- `SDP_API_HOST`
- `SDP_API_PORT`
- `SDP_PUBLIC_BASE_URL`
- `SDP_LOG_LEVEL`
- `SDP_LOG_JSON`
- `SDP_CONTROL_PLANE_DSN`
- `SDP_ARTIFACT_ROOT`
- `SDP_BASELINE_ASSET_ROOT`
- `SDP_ENABLED_ENGINES`

Endpoint operativi:
- `GET /health`
- `GET /health/live`
- `GET /health/ready`
- `GET /metrics`

### Worker production commands
Esempi:
```bash
SDP_WORKER_KIND=publish .venv/bin/python -m sanitized_data_platform.bootstrap.worker_runtime
SDP_WORKER_KIND=extraction .venv/bin/python -m sanitized_data_platform.bootstrap.worker_runtime
SDP_WORKER_KIND=artifact_publish .venv/bin/python -m sanitized_data_platform.bootstrap.worker_runtime
SDP_WORKER_KIND=baseline_refresh .venv/bin/python -m sanitized_data_platform.bootstrap.worker_runtime
SDP_WORKER_KIND=refresh_schedule_dispatch .venv/bin/python -m sanitized_data_platform.bootstrap.worker_runtime
SDP_WORKER_KIND=artifact_retention .venv/bin/python -m sanitized_data_platform.bootstrap.worker_runtime
SDP_WORKER_KIND=artifact_cleanup .venv/bin/python -m sanitized_data_platform.bootstrap.worker_runtime
SDP_WORKER_KIND=stale_job_recovery .venv/bin/python -m sanitized_data_platform.bootstrap.worker_runtime
```

### Frontend
```bash
cd frontend/app
npm install
npm run dev
```

Se il backend gira sulla porta standard `8000`, Vite proxy inoltra automaticamente `/api`, `/health`, `/metrics`, `/docs` e `/openapi.json`.

### Compose stack
```bash
docker compose up --build
```

Nota:
- la stack Compose usa ora `SDP_BOOTSTRAP_MODE=seed` con control-plane PostgreSQL reale
- al primo avvio il control plane viene migrato e seedato in modo durevole
- i worker usano ancora queue polling semplice come passo intermedio prima del leasing persistente
- la stack avvia anche worker separati per publish, extraction, artifact publish e baseline refresh
- i worker maintenance (`refresh_schedule_dispatch`, `artifact_retention`, `artifact_cleanup`, `stale_job_recovery`) sono inclusi come servizi dedicati one-shot

### Test
```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
cd frontend/app && npm run test
```

## Documentazione
- `docs/architecture/overview.md`
- `docs/architecture/domain-model.md`
- `docs/architecture/components.md`
- `docs/architecture/sequence-flows.md`
- `docs/security/security-model.md`
- `docs/api/api-outline.md`
- `docs/adr/`
- `docs/runbooks/production-core.md`
- `docs/runbooks/worker-recovery.md`

## Principi
- core agnostico dalla tecnologia
- adapter per database vendor-specific
- control plane separato dal data plane
- policy centralizzate
- audit e lineage obbligatori

# Production Core Runtime

## Scope
Questo runbook descrive il runtime operativo introdotto per il passaggio da composition demo a runtime production-friendly.

## Configurazione
Il runtime legge configurazione da environment tramite `sanitized_data_platform.config.PlatformSettings`.

Variabili chiave:
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
- `SDP_WORKER_POLL_INTERVAL_SECONDS`
- `SDP_WORKER_HEARTBEAT_INTERVAL_SECONDS`
- `SDP_WORKER_BURST_SIZE`
- `SDP_ARTIFACT_ROOT`
- `SDP_BASELINE_ASSET_ROOT`
- `SDP_ENABLED_ENGINES`

## Health e osservabilità
Endpoint standard:
- `GET /health`: liveness compatto
- `GET /health/live`: liveness esplicito
- `GET /health/ready`: readiness con dettaglio dipendenze
- `GET /metrics`: metriche runtime serializzate in JSON

Il transport FastAPI aggiunge:
- `X-Request-ID` su ogni risposta HTTP
- logging strutturato per request completate e failure non gestite

## Bootstrap
Per runtime locali seedati:

```bash
SDP_BOOTSTRAP_MODE=seed \
SDP_CONTROL_PLANE_DSN=postgresql://sanitized:sanitized@localhost:5432/sanitized_control_plane \
.venv/bin/uvicorn sanitized_data_platform.bootstrap.production:create_production_fastapi_app --factory
```

Per runtime realmente production:
- costruire un `ApiApp` completamente wired con repository persistenti e adapter reali
- usare `ControlPlaneJsonStore` con backend PostgreSQL (`PsycopgBackend`) per lo stato durevole del control plane
- iniettare quell'`ApiApp` in `build_production_runtime(...)`
- mantenere `SDP_BOOTSTRAP_MODE=production` oppure `seed` per bootstrap iniziale controllato

## Worker runtime
Entry point:

```bash
SDP_WORKER_KIND=<kind> .venv/bin/python -m sanitized_data_platform.bootstrap.worker_runtime
```

Valori supportati per `SDP_WORKER_KIND`:
- `publish`
- `extraction`
- `artifact_publish`
- `baseline_refresh`
- `refresh_schedule_dispatch`
- `artifact_retention`
- `artifact_cleanup`
- `stale_job_recovery`

Variabili utili:
- `SDP_WORKER_ID`
- `SDP_WORKER_MAX_CYCLES`
- `SDP_WORKER_POLL_INTERVAL_SECONDS`
- `SDP_WORKER_HEARTBEAT_INTERVAL_SECONDS`
- `SDP_WORKER_BURST_SIZE`

## Compose deployment
La stack `compose.yml` avvia:
- `api`
- `control-plane-postgres`
- `frontend`
- `worker-publish`
- `worker-extraction`
- `worker-artifact-publish`
- `worker-baseline-refresh`
- `worker-refresh-schedule-dispatch`
- `worker-artifact-retention`
- `worker-artifact-cleanup`
- `worker-stale-job-recovery`

I worker di maintenance sono configurati come run controllati con `SDP_WORKER_MAX_CYCLES=1`.

## Limiti attuali
- l'API production usa repository persistenti; il prossimo passo resta l'hardening dei worker con lease/heartbeat persistenti
- la modalità `demo` resta utile per smoke test UI/API totalmente in-memory

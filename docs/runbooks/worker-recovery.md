# Worker Recovery

## Obiettivo
Documentare il comportamento attuale dei worker e il recovery model minimo prima del passaggio al queueing persistente.

## Stato attuale
I workflow separati restano:
- publish
- extraction
- artifact publish
- baseline refresh
- refresh schedule dispatch
- artifact retention
- artifact cleanup

I worker applicano transizioni di stato esplicite a livello dominio e scrivono audit/lineage dove previsto.

## Cosa monitorare
- job fermi in stato `running`, `planning` o `publishing`
- artifact `expired` non ancora `deleted`
- baseline refresh falliti con asset parziali
- audit event di failure per i job asincroni

## Recovery operativo attuale
- usare gli endpoint API di dettaglio per job, audit e lineage
- verificare `GET /health/ready` e `GET /metrics` prima di riavviare componenti
- se si usa la composition demo, riavvio del processo implica reset dello stato seedato
- usare il runner:

```bash
SDP_WORKER_KIND=stale_job_recovery .venv/bin/python -m sanitized_data_platform.bootstrap.worker_runtime
```

- il recovery corrente riporta in coda i job rimasti in stato attivo ma senza lease valida:
  - publish `planning/publishing -> pending`
  - extraction `running -> requested`
  - artifact publish `publishing -> pending`
  - baseline refresh `running -> requested`

## Prossimo hardening previsto
- polling persistente con lease/heartbeat su PostgreSQL
- idempotent claiming dei job
- cleanup più esplicito di artifact e baseline asset interrotti

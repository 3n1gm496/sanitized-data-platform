# Sanitized Data Platform

Piattaforma interna on-prem per il provisioning self-service di copie sanitizzate e governate dei dati di produzione verso ambienti non-production.

## Obiettivo
Consentire a sviluppatori e tester di ottenere dataset coerenti, mascherati e auditabili per DEV, TEST e COLLAUDO, senza accesso diretto ai dati reali di produzione.

## Stato
Bootstrap iniziale del repository.

## Documentazione
- `docs/architecture/overview.md`
- `docs/architecture/domain-model.md`
- `docs/architecture/components.md`
- `docs/architecture/sequence-flows.md`
- `docs/security/security-model.md`
- `docs/api/api-outline.md`
- `docs/adr/`

## Principi
- core agnostico dalla tecnologia
- adapter per database vendor-specific
- control plane separato dal data plane
- policy centralizzate
- audit e lineage obbligatori

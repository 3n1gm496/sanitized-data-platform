# API Outline

## Purpose

Questo documento definisce l’outline iniziale delle API REST della piattaforma.

Le API sono pensate per supportare la Web UI e client interni.

## API principles

- API-first
- naming semplice e coerente
- separazione tra risorse di catalogo, risorse operative e risorse di audit
- endpoint iniziali focalizzati sul simple mode
- nessuna esposizione di dettagli sensibili non necessari

## Base path

Valore iniziale proposto:

`/api/v1`

## Main resource groups

- systems
- environments
- dataset-profiles
- jobs
- audit-events
- metadata
- policies

## 1. Systems

### GET /api/v1/systems

Restituisce i sistemi disponibili per l’utente.

### Response example

```json
[
  {
    "systemId": "crm",
    "name": "CRM",
    "sourceEngine": "postgres",
    "availableProfiles": 3
  }
]

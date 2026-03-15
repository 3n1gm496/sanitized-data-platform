# ADR 0001 — Monorepo and Core Abstractions

## Status

Accepted

## Context

La piattaforma Sanitized Data Platform richiede:

- un core indipendente dalla tecnologia
- una forte coerenza tra documentazione, API e codice
- supporto futuro a più database e più adapter
- separazione netta tra dominio, orchestrazione e integrazioni
- possibilità di evoluzione incrementale senza introdurre presto coupling vendor-specific

Il progetto parte come iniziativa interna on-prem e deve rimanere realistico come MVP.

## Decision

Si decide di adottare:

1. **monorepo singolo**
2. **core domain technology-agnostic**
3. **adapter/plugin model per i dettagli vendor-specific**
4. **separazione tra control plane e data plane**
5. **documentazione architetturale come baseline prima dello sviluppo funzionale**

## Rationale

## Monorepo

Il monorepo consente di mantenere nello stesso repository:

- documentazione architetturale
- API outline
- sicurezza
- scaffold del core
- adapter
- test

Questo è coerente con la necessità iniziale di far evolvere in parallelo:

- modello di dominio
- contratti
- orchestrazione
- worker
- API

## Technology-agnostic core

Il core deve modellare concetti stabili:

- DataSource
- TargetEnvironment
- DatasetProfile
- PublishJob
- TransformationPolicy
- AuditEvent
- MetadataObject
- Relationship

e non dettagli fisici dei database.

## Adapter model

Le specificità di Oracle, SQL Server, PostgreSQL, MySQL e altri sistemi devono essere incapsulate in adapter.

Questo approccio:

- limita il coupling
- rende più testabile il core
- permette sviluppo incrementale dei connettori

## Control plane / data plane split

La separazione è adottata per:

- chiarezza architetturale
- migliore isolamento delle responsabilità
- maggiore controllo di sicurezza
- minore contaminazione del dominio con logica di trasporto o integrazione

## Consequences

## Positive consequences

- migliore manutenibilità
- migliore chiarezza del dominio
- facilità di scaffolding iniziale
- maggiore allineamento tra documentazione e codice
- evoluzione più disciplinata verso nuovi adapter

## Negative consequences

- maggiore numero iniziale di moduli astratti
- rischio di astrazione prematura se non controllata
- necessità di disciplina forte nella gestione dei boundary

## Rejected alternatives

## 1. Start directly from one database vendor

Scartata perché introdurrebbe coupling troppo presto e comprometterebbe il requisito di agnosticismo architetturale.

## 2. Generic ETL-style architecture

Scartata perché il prodotto non è un ETL generico ma una sanitized data delivery platform governata da policy.

## 3. Live proxy to production

Scartata perché aumenta rischio, complessità operativa e accoppiamento con i sistemi di runtime.

## 4. Separate repositories from day one

Scartata nell’MVP perché aumenterebbe overhead di coordinamento senza beneficio immediato.

## Implementation notes

Nelle prime iterazioni il repository dovrà privilegiare:

- documentazione
- modello di dominio
- porte e contratti
- skeleton applicativo
- test di dominio

I connettori reali verranno introdotti in modo incrementale.

## Follow-up decisions expected

ADR successivi dovranno coprire:

- scelta stack backend
- scelta scheduler/orchestrator
- design del token vault
- strategia baseline sanitizzate
- strategia di validation
- supporto iniziale ai database

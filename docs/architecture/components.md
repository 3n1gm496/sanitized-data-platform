# Components

## Purpose

Questo documento descrive i componenti principali della piattaforma e le loro responsabilità.

## System decomposition

La piattaforma è divisa in:

- Control Plane
- Data Plane
- Shared infrastructure capabilities

---

## Control Plane

## 1. Web UI

### Responsibility
Fornire l’interfaccia utente self-service per:

- selezione sistema
- selezione ambiente target
- selezione dataset profile
- avvio publish
- monitoraggio job
- consultazione audit e lineage

### Notes
La UX iniziale deve essere estremamente semplice.
La modalità avanzata verrà aggiunta successivamente.

---

## 2. REST API

### Responsibility
Esporre funzionalità applicative verso UI e client interni.

### Main capabilities
- listare sistemi disponibili
- listare ambienti disponibili
- listare dataset profiles
- creare publish job
- leggere stato job
- leggere eventi audit
- leggere catalogo metadati essenziale

---

## 3. Identity and RBAC

### Responsibility
Gestire autenticazione, autorizzazione e ruoli.

### Initial roles
- Admin
- Data Steward / Security
- Developer / Tester

### Notes
Le azioni di reverse tokenization non devono essere disponibili a ruoli generici.

---

## 4. Metadata Catalog

### Responsibility
Mantenere rappresentazione centralizzata di:

- sorgenti
- schemi
- tabelle
- colonne
- relazioni
- classificazioni
- policy associate

### Notes
Il catalogo è il cuore del governo del dato.

---

## 5. Policy Engine

### Responsibility
Determinare:

- quali dataset profile sono disponibili
- quali trasformazioni applicare
- quali colonne non possono uscire
- quando è richiesta approvazione
- quali controlli eseguire prima della pubblicazione

### Notes
Le policy devono essere centralizzate e versionabili.

---

## 6. Job Orchestrator

### Responsibility
Gestire il ciclo di vita dei publish job.

### Main capabilities
- enqueue
- scheduling
- retry
- stato
- errore
- completamento
- integrazione con worker

---

## 7. Audit and Lineage

### Responsibility
Registrare:

- chi ha richiesto cosa
- quando
- da quale sorgente
- verso quale target
- con quali regole
- con quale esito

### Notes
Audit e lineage sono obbligatori in ogni esecuzione.

---

## Data Plane

## 8. Source Connectors

### Responsibility
Leggere dati e metadati dalle sorgenti supportate.

### Constraints
- preferibilmente agentless
- preferenza a replica o snapshot
- logica vendor-specific isolata

### Initial scope
Adapter reali iniziali per:
- PostgreSQL
- Oracle

### Future scope
Adapter futuri possibili:
- SQL Server
- MySQL
- MongoDB

---

## 9. Metadata Discovery

### Responsibility
Scoprire:

- schemi
- tabelle
- colonne
- tipi
- PK/FK
- viste
- sequence di base

### Notes
Le relazioni mancanti potranno essere inferite o definite manualmente.
Nel runtime attuale PostgreSQL e Oracle hanno discovery reale e parità sui workflow principali.

---

## 10. Relationship Resolver

### Responsibility
Costruire il grafo delle relazioni tramite:

- FK dichiarate
- inferenza
- configurazione manuale

### Notes
È un componente chiave per la coerenza cross-table.

---

## 11. Classification Engine

### Responsibility
Classificare i dati sensibili usando:

- naming rules
- pattern
- regex
- profiling di campioni
- approvazione manuale

### Output
- SensitivityTag
- candidate policies
- warning su zone non classificate

---

## 12. Transformation Engine

### Responsibility
Applicare trasformazioni ai dati in base alle policy.

### Supported transformation families
- deterministic pseudonymization
- irreversible masking
- reversible tokenization
- hashing
- synthetic replacement
- generalization
- redaction

### Notes
La coerenza dei valori trasformati tra tabelle è obbligatoria.

---

## 13. Token Vault Integration

### Responsibility
Gestire le operazioni di tokenizzazione reversibile in modo isolato.

### Constraints
- accesso ristretto
- chiavi fuori dal core applicativo
- audit delle operazioni di reverse
- nessuna disponibilità diretta agli sviluppatori

---

## 14. Validation Engine

### Responsibility
Validare il dataset pubblicato.

### Validation categories
- row counts
- referential integrity
- format compatibility
- policy coverage
- execution sanity checks

---

## 15. Publish Engine

### Responsibility
Scrivere i dati sanitizzati verso l’ambiente target.

### Constraints
- stesso engine della sorgente nella prima implementazione
- rispetto dell’ordine di caricamento
- gestione di identity/sequence
- supporto a baseline sanitizzate

---

## Shared capabilities

## 16. Scheduler

### Responsibility
Gestire pianificazioni ricorrenti e publish giornalieri.

---

## 17. Secrets and configuration management

### Responsibility
Gestire credenziali, riferimenti a chiavi e configurazioni sensibili.

### Constraints
- nessun segreto hardcoded
- vault o sistema equivalente
- separazione dei segreti per source, target e token services

---

## 18. Observability

### Responsibility
Fornire logging, metriche, tracing e diagnostica.

---

## Primary dependencies between components

Dipendenze principali:

- Web UI -> REST API
- REST API -> Application services
- Application services -> Policy Engine
- Application services -> Job Orchestrator
- Job Orchestrator -> Workers
- Workers -> Source Connectors
- Workers -> Metadata Discovery
- Workers -> Relationship Resolver
- Workers -> Transformation Engine
- Workers -> Validation Engine
- Workers -> Publish Engine
- Workers -> Audit and Lineage
- Transformation Engine -> Token Vault Integration

## MVP implementation focus

Per l’MVP l’attenzione iniziale va su:

- Metadata Catalog
- Policy Engine
- Job Orchestrator
- Transformation Engine
- Publish Engine
- Audit and Lineage
- REST API skeleton
- Worker skeleton

## Risks

Rischi principali per componente:

- Metadata Catalog: incompletezza metadati
- Relationship Resolver: relazioni non dichiarate
- Classification Engine: falsi positivi e falsi negativi
- Transformation Engine: perdita di semantica
- Token Vault: esposizione indebita della reversibilità
- Publish Engine: performance e vincoli
- Audit: inconsistenza con l’esecuzione reale

# Architecture Overview

## Purpose

Sanitized Data Platform è una piattaforma interna on-prem per il provisioning self-service di copie sanitizzate, coerenti e governate dei dati di produzione verso ambienti non-production.

Gli ambienti target iniziali sono:

- DEV
- TEST
- COLLAUDO

L’ambiente di produzione rimane l’unico ambiente con dati reali.

## Scope

La piattaforma deve consentire agli utenti interni di:

- richiedere dataset per ambienti non-prod in modalità self-service
- usare profili di dataset predefiniti
- ottenere dati coerenti tra tabelle e domini applicativi
- applicare regole centralizzate di masking, pseudonymization, tokenization e trasformazione
- mantenere audit, lineage e controllo degli accessi
- pubblicare i dati nel medesimo engine del database sorgente nella prima implementazione

## Non-goals

Questa piattaforma non è:

- un live proxy verso produzione
- un prodotto ETL generico
- un sistema di replica real-time verso ambienti non-prod
- una piattaforma multi-tenant
- una soluzione cloud-first
- un sistema che consente agli sviluppatori di definire liberamente policy di sicurezza

## Operating assumptions

Le assunzioni iniziali sono:

- deployment on-prem
- singola organizzazione
- sorgenti lette preferibilmente da replica, snapshot, restore point o sorgenti equivalenti
- target dello stesso tipo del database sorgente
- modalità standard iniziale: full sanitized clone
- supporto futuro a subset e scenario dataset
- integrazioni preferibilmente agentless
- dataset grandi
- publish veloce ottenuto tramite baseline sanitizzate precompute

## High-level architecture

La piattaforma è divisa in due aree principali:

- **Control Plane**
- **Data Plane**

### Control Plane

Il Control Plane governa il sistema e contiene:

- Web UI
- REST API
- Identity and RBAC
- Metadata Catalog
- Policy Engine
- Job Orchestrator
- Audit and Lineage services
- Dataset profile management

### Data Plane

Il Data Plane esegue il lavoro sui dati e contiene:

- Source connectors
- Metadata discovery
- Extraction engine
- Relationship resolver
- Classification engine
- Transformation engine
- Token vault integration
- Validation engine
- Publish engine

## Architectural principles

## 1. Technology-agnostic core

Il core del sistema deve essere indipendente dai dettagli fisici di Oracle, SQL Server, PostgreSQL, MySQL, MongoDB e altri sistemi.

Il core ragiona in termini di:

- sistemi sorgente
- ambienti
- dataset profile
- tabelle
- colonne
- relazioni
- policy
- job
- eventi di audit

## 2. Vendor-specific adapters

Le differenze tecnologiche devono essere gestite tramite adapter/plugin.

Il core non deve contenere logica specifica del vendor.

## 3. Control plane / data plane separation

Le responsabilità di orchestrazione e governance devono essere separate dalle responsabilità di accesso, trasformazione e pubblicazione dei dati.

## 4. Security by design

La piattaforma deve assumere che i dati trattati siano sensibili per default e deve applicare:

- least privilege
- policy centralizzate
- audit obbligatorio
- separazione delle responsabilità
- reversibilità selettiva e isolata

## 5. Fast publish through sanitized baselines

Il sistema deve preferire la creazione di baseline sanitizzate precompute, aggiornate periodicamente, da cui derivare publish veloci verso gli ambienti target.

## 6. Self-service with guardrails

L’utente finale deve avere un’esperienza semplice ma governata:

1. choose system
2. choose target environment
3. choose dataset profile
4. run

Le decisioni di sicurezza e trasformazione restano centralizzate.

## Core user experience

La modalità standard deve essere semplice e adatta a tutti gli sviluppatori.

Flusso standard:

1. l’utente seleziona un sistema applicativo
2. seleziona l’ambiente target
3. seleziona un dataset profile approvato
4. avvia il publish
5. monitora stato e audit del job

La modalità avanzata, introdotta successivamente, potrà consentire filtri, subset, scheduling e profili personalizzati.

## MVP boundaries

La prima versione deve concentrarsi su:

- documentazione architetturale forte
- core domain model
- metadata catalog iniziale
- policy model
- audit model
- dataset profiles
- full sanitized clone
- same-engine delivery
- baseline sanitizzate
- skeleton di adapter DB
- API e worker scaffolding

Non sono in scope MVP:

- connettori completi per tutti i database
- CDC cross-engine
- subset intelligenti completi
- redazione avanzata di blob e documenti
- supporto completo a oggetti DB vendor-specific complessi
- UI completa di amministrazione avanzata

## Main risks

I rischi principali sono:

- relazioni tra tabelle non dichiarate
- coerenza semantica insufficiente dopo il masking
- complessità delle trasformazioni reversibili
- performance su dataset molto grandi
- gestione di testo libero, blob e allegati
- sovraestensione troppo precoce verso molti database

## Next steps

I prossimi passi sono:

1. definire il canonical domain model
2. definire i componenti principali
3. definire i flussi end-to-end
4. definire il security model
5. definire l’outline delle API
6. creare scaffold coerente di codice

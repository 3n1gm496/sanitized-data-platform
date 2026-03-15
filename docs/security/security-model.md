# Security Model

## Purpose

Questo documento descrive il modello di sicurezza iniziale della piattaforma.

La piattaforma tratta dati potenzialmente altamente sensibili. La sicurezza non è un aspetto accessorio ma una proprietà strutturale del sistema.

## Security objectives

Obiettivi principali:

- impedire esposizione diretta dei dati reali di produzione agli ambienti non-prod
- garantire trasformazione governata dei dati sensibili
- limitare la reversibilità ai soli casi autorizzati
- assicurare audit e tracciabilità completi
- ridurre la superficie di attacco
- rispettare il principio del least privilege

## Core assumptions

Assunzioni iniziali:

- deployment on-prem
- singola organizzazione
- ambienti non-prod meno affidabili della produzione
- utenti developer/tester non autorizzati a vedere dati originali
- alcune trasformazioni possono essere reversibili ma solo tramite componente isolato
- i segreti e le chiavi devono essere fuori dal codice applicativo

## Security principles

## 1. No direct non-prod access to production

Nessun ambiente DEV, TEST o COLLAUDO deve avere accesso diretto ai dati reali di produzione.

Le letture devono avvenire preferibilmente da:

- replica
- snapshot
- restore point
- sorgente equivalente controllata

## 2. Least privilege

Ogni componente e ogni utente deve avere solo i permessi minimi necessari.

## 3. Centralized policies

Le regole di masking, tokenization e classificazione devono essere centralizzate.

Gli utenti finali non definiscono liberamente policy di sicurezza.

## 4. Separation of duties

I ruoli tecnici e di sicurezza devono essere separati.

## 5. Selective reversibility

La reversibilità è permessa solo in casi specifici e deve essere gestita da un servizio isolato.

## 6. Full auditability

Ogni azione sensibile deve essere tracciata.

## Roles

## Admin

Responsabilità:

- configurazione sorgenti e target
- gestione componenti di piattaforma
- gestione configurazioni operative

Non deve avere automaticamente accesso alle operazioni di reverse.

## Data Steward / Security

Responsabilità:

- approvazione classificazioni
- approvazione policy
- gestione dei domini di tokenizzazione
- autorizzazione e controllo sulle operazioni reversibili

## Developer / Tester

Responsabilità:

- richiesta dataset
- monitoraggio job
- uso di dataset pubblicati

Non può vedere dati originali né eseguire reverse tokenization.

## Sensitive data categories

Categorie iniziali:

- dati personali diretti
- dati finanziari
- dati sanitari
- identificativi governativi
- credenziali e segreti
- note e testo libero sensibile
- allegati e documenti
- dati operativi interni riservati

## Transformation security model

## Deterministic pseudonymization

Uso:
- mantenere coerenza cross-table
- ridurre esposizione

Vincoli:
- nessuna reversibilità implicita
- consistenza garantita

## Irreversible masking

Uso:
- dati che non devono mai essere recuperati
- segreti o campi ad alto rischio

## Reversible tokenization

Uso:
- solo quando il reverse è un requisito esplicito e giustificato

Vincoli:
- token vault dedicato
- chiavi esterne al core
- reverse sotto RBAC stretto
- audit obbligatorio

## Hashing

Uso:
- matching controllato
- non per dati che richiedono ricostruzione

## Synthetic replacement

Uso:
- mantenimento di dataset applicativamente plausibili

Vincoli:
- attenzione a formato, lunghezza e semantica

## Generalization

Uso:
- riduzione di precisione per abbassare il rischio

Esempi:
- età -> range
- data di nascita -> anno
- importo -> bucket

## Token vault model

Il token vault è un componente separato dal core applicativo.

Responsabilità:

- generare token
- mantenere mapping reversibile
- controllare chi può eseguire reverse
- auditare ogni operazione sensibile

Vincoli:

- nessun accesso diretto per developer/tester
- chiavi o materiali crittografici gestiti fuori dal repository
- logging dedicato
- forte controllo degli accessi

## Secrets management

Regole:

- nessun segreto hardcoded
- nessuna chiave nel repository
- credenziali separate per source, target e servizi interni
- integrazione con vault o sistema equivalente
- rotazione periodica dei segreti

## Data in transit and at rest

Requisiti iniziali:

- cifratura in transito per connessioni verso sorgenti e target
- cifratura at-rest per dati persistiti dalla piattaforma
- protezione specifica dei dati di audit contenenti informazioni sensibili

## Audit requirements

Devono essere auditate almeno queste azioni:

- login e accessi amministrativi
- creazione e avvio publish job
- cambi di policy
- discovery e classificazione
- tokenizzazione reversibile
- reverse tokenization
- fallimenti di validazione
- pubblicazione completata

## Lineage requirements

Ogni publish deve poter essere ricostruito in termini di:

- sorgente usata
- baseline usata
- policy applicate
- target pubblicato
- timestamp
- attore
- esito

## Security controls by layer

## UI/API layer
- autenticazione
- autorizzazione RBAC
- input validation
- rate limiting dove necessario
- audit degli endpoint sensibili

## Orchestration layer
- validazione delle policy prima dell’esecuzione
- enforcement dei ruoli
- segregazione dei job

## Data plane layer
- source credentials minime
- target credentials separate
- controlli sulle operazioni di export/import
- masking prima della pubblicazione

## Token layer
- isolamento logico e operativo
- controllo forte sui reverse flows

## Known risks

Rischi principali:

- uso improprio della reversibilità
- incompletezza della classificazione
- dati sensibili nascosti in testo libero o blob
- drift tra policy documentate e policy applicate
- accessi eccessivi ai target
- logging insufficiente

## MVP security scope

In scope per MVP:

- RBAC di base
- audit completo
- secrets management esterno
- token vault astratto nel design
- policy enforcement
- no direct production access
- same-engine publish
- validation minima obbligatoria

Fuori scope MVP:

- advanced document redaction
- DLP avanzato
- automatic discovery perfetta di testo libero
- integrazioni complete con tutti i sistemi enterprise di sicurezza

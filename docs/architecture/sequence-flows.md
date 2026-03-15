# Sequence Flows

## Purpose

Questo documento descrive i flussi principali end-to-end della piattaforma.

## Flow 1 — standard self-service publish

### Goal
Consentire a un utente interno di pubblicare un dataset sanitizzato in un ambiente non-prod tramite un profilo approvato.

### Sequence

1. L’utente apre la Web UI
2. La Web UI richiama la REST API
3. La REST API legge:
   - sistemi disponibili
   - ambienti disponibili
   - dataset profiles disponibili per l’utente
4. L’utente seleziona:
   - system
   - target environment
   - dataset profile
5. La REST API valida autorizzazioni e policy
6. La REST API crea un PublishJob
7. Il Job Orchestrator mette il job in coda
8. Un worker prende in carico il job
9. Il worker determina la baseline sanitizzata più adatta oppure pianifica la generazione
10. Il worker esegue controlli preliminari
11. Il worker avvia extract/transform/validate/publish
12. Il worker aggiorna stato e audit
13. La UI mostra stato e risultato finale

### Output
- dataset pubblicato
- job status finale
- audit trail
- lineage references

---

## Flow 2 — daily sanitized baseline refresh

### Goal
Rigenerare o aggiornare una baseline sanitizzata da usare per publish veloci.

### Sequence

1. Lo Scheduler attiva il refresh giornaliero
2. Il Job Orchestrator crea un baseline refresh job
3. Un worker legge dalla sorgente sicura:
   - replica
   - snapshot
   - restore point
4. Il worker esegue metadata discovery o usa il catalogo disponibile
5. Il worker risolve relazioni rilevanti
6. Il worker applica classificazione e policy
7. Il worker trasforma i dati
8. Il worker esegue validation
9. Il worker pubblica o aggiorna la baseline sanitizzata
10. Il worker registra audit e lineage
11. Il catalogo aggiorna la baseline disponibile per i publish successivi

### Output
- sanitized baseline aggiornata
- audit tecnico
- disponibilità per publish veloce

---

## Flow 3 — metadata discovery and policy coverage

### Goal
Scoprire metadati e verificare copertura delle policy prima di autorizzare publish.

### Sequence

1. Un amministratore o job tecnico attiva discovery
2. Il Metadata Discovery interroga la sorgente
3. Schemi, tabelle, colonne e relazioni vengono registrati nel catalogo
4. Il Classification Engine analizza le colonne
5. Vengono proposti sensitivity tags
6. Il Policy Engine verifica quali colonne non hanno policy
7. Il sistema marca eventuali gap
8. Il Data Steward approva o corregge classificazioni e policy

### Output
- catalogo aggiornato
- classificazioni candidate
- gap di governance espliciti

---

## Flow 4 — reversible tokenization

### Goal
Applicare tokenizzazione reversibile in modo isolato e auditato.

### Sequence

1. Il Transformation Engine incontra una policy reversibile
2. Il Transformation Engine invoca il Token Vault
3. Il Token Vault genera o recupera il token
4. Il valore tokenizzato viene restituito al motore
5. Il dataset continua il flusso senza esporre il valore originale
6. Le operazioni sensibili vengono auditate

### Reverse flow
1. Un utente autorizzato richiede reverse
2. Il sistema verifica ruolo e contesto
3. Il Token Vault esegue reverse
4. L’operazione viene audidata
5. Il valore non viene propagato oltre il contesto autorizzato

### Constraints
- nessun reverse per ruoli developer/tester
- audit obbligatorio
- chiavi isolate
- accesso minimo

---

## Flow 5 — validation before publish completion

### Goal
Assicurare che il dataset pubblicato sia coerente e utilizzabile.

### Sequence

1. Terminata la trasformazione, il worker invoca il Validation Engine
2. Il sistema esegue controlli su:
   - row counts
   - referential integrity
   - transformation coverage
   - formati compatibili
   - sanity checks base
3. Se i controlli falliscono:
   - il job viene marcato failed
   - l’audit registra l’errore
4. Se i controlli passano:
   - il publish viene finalizzato
   - il job viene marcato completed

---

## Flow 6 — advanced mode future flow

### Goal
Supportare in futuro subset e dataset scenario-based.

### Planned sequence
1. L’utente entra in modalità avanzata
2. Seleziona filtri, finestre temporali o subset profiles
3. Il sistema costruisce un extraction plan
4. Il Relationship Resolver espande il grafo dati
5. Il resto del flusso rimane identico a quello standard

### Note
Questo flusso non è incluso nell’MVP iniziale.

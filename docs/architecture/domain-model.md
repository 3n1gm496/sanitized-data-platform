# Domain Model

## Purpose

Questo documento definisce il modello di dominio concettuale iniziale della piattaforma.

L’obiettivo è creare un linguaggio comune e un insieme di astrazioni indipendenti dal vendor database.

## Design principles

Il dominio deve essere:

- technology-agnostic
- stabile
- orientato a policy e workflow
- separato dai dettagli di infrastruttura
- estensibile a più engine e più modalità di dataset

## Core domain entities

## DataSource

Rappresenta una sorgente da cui la piattaforma può leggere dati o metadati.

Attributi tipici:

- source_id
- system_name
- engine_type
- endpoint
- database_name
- access_mode
- replica_preferred
- active

Note:
- non implica accesso alla produzione primaria
- rappresenta preferibilmente replica, snapshot o sorgente sicura equivalente

## TargetEnvironment

Rappresenta un ambiente di destinazione.

Attributi tipici:

- environment_id
- name
- environment_type
- engine_type
- target_endpoint
- active

Esempi:
- dev
- test
- collaudo

## DatasetProfile

Rappresenta un profilo riusabile per la generazione di un dataset.

Attributi tipici:

- profile_id
- name
- system_name
- dataset_mode
- target_environment_type
- uses_sanitized_baseline
- preserve_constraints
- requires_approval
- active

Esempi:
- full_sanitized_clone
- daily_qa_baseline
- regression_dataset

## PublishJob

Rappresenta una richiesta o esecuzione di publish.

Attributi tipici:

- job_id
- source_id
- target_environment_id
- dataset_profile_id
- requested_by
- status
- created_at
- updated_at
- execution_summary

## TransformationPolicy

Rappresenta una policy di trasformazione applicata a un dato elemento.

Attributi tipici:

- policy_id
- system_name
- object_name
- column_name
- sensitivity_tag
- transformation_type
- reversible
- preserve_format
- preserve_length
- active

## AuditEvent

Rappresenta un evento auditabile.

Attributi tipici:

- event_id
- event_type
- actor
- subject_type
- subject_id
- details
- created_at

## MetadataObject

Entità concettuale per rappresentare un oggetto del catalogo.

Tipi possibili:

- schema
- table
- column
- relationship
- index
- view
- sequence

## Relationship

Rappresenta una relazione semantica o tecnica tra oggetti.

Attributi tipici:

- relationship_id
- source_object
- target_object
- relationship_type
- inferred
- confidence
- active

Può essere:
- dichiarata
- inferita
- manualmente registrata

## SensitivityTag

Rappresenta la classificazione di sensibilità di una colonna o campo.

Esempi:

- pii.name
- pii.email
- pii.phone
- pii.gov_id
- pii.financial
- pii.health
- secret.credential
- free_text.sensitive
- internal.operational

## TokenizationDomain

Rappresenta un dominio di tokenizzazione reversibile.

Serve per isolare mapping e regole di reverse.

Attributi tipici:

- domain_id
- name
- allowed_roles_for_reverse
- key_reference
- active

## Canonical metadata model

Il modello canonico serve a separare il dominio dai tipi fisici del database.

## Logical object hierarchy

- System
- DataSource
- Schema
- Table
- Column
- Relationship
- DatasetProfile
- TransformationPolicy
- PublishJob
- AuditEvent

## Logical data types

I tipi fisici dei database devono essere normalizzati in un set di tipi logici.

Tipi logici iniziali:

- string
- integer
- decimal
- boolean
- date
- timestamp
- json
- binary
- large_text
- large_binary
- identifier

## Enumerations

## DatabaseEngine

Valori iniziali previsti:

- postgres
- sqlserver
- oracle
- mysql
- mongodb

## DatasetMode

Valori iniziali:

- full_clone
- subset
- scenario

## JobStatus

Valori iniziali:

- pending
- planning
- extracting
- transforming
- validating
- publishing
- completed
- failed
- cancelled

## TransformationType

Valori iniziali:

- deterministic_pseudonymization
- irreversible_masking
- reversible_tokenization
- hashing
- synthetic_replacement
- generalization
- redaction

## Aggregates and boundaries

## Dataset provisioning aggregate

Include:

- DatasetProfile
- PublishJob
- TargetEnvironment
- execution state

## Metadata governance aggregate

Include:

- MetadataObject
- Relationship
- SensitivityTag
- TransformationPolicy

## Audit aggregate

Include:

- AuditEvent
- lineage references
- execution references

## Invariants

Le invarianti iniziali di dominio sono:

- un PublishJob deve riferirsi a un DatasetProfile valido
- il target engine deve essere compatibile con il source engine nella prima implementazione
- una policy reversibile richiede un TokenizationDomain valido
- un dataset in simple mode deve essere associato a un profilo approvato
- tutte le colonne sensibili devono avere una policy associata prima del publish
- ogni esecuzione deve produrre eventi di audit

## Assumptions

Assunzioni iniziali:

- il dominio è modellato per sistemi relazionali in prima battuta
- il supporto documentale e blob sarà inizialmente limitato
- le relazioni possono essere incomplete o inferite
- i profili dataset sono definiti centralmente

## Open questions

Da validare nelle fasi successive:

- modellazione esplicita delle versioni delle policy
- rappresentazione delle baseline sanitizzate come entità di dominio separata
- rappresentazione esplicita dei lineage edges
- granularità dei permessi per reverse tokenization

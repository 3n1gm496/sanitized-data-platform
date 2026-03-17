# AGENTS.md

## Mission

Build an internal on-prem sanitized data delivery platform that provisions policy-governed copies of production data into non-production environments.

The platform must enable safe, auditable, repeatable delivery of sanitized datasets for development and testing.

This is a **sanitized data delivery platform**, not a generic ETL tool and not a production proxy.

---

# Product Scope

The platform provisions sanitized data into:

- DEV
- TEST
- COLLAUDO

Production remains the **only environment containing real data**.

The system must support both:

- **baseline-based provisioning** (fast clone from precomputed sanitized datasets)
- **artifact-based delivery** (extraction → artifact → delivery)

---

# Core Platform Capabilities

The system must provide the following capabilities:

### Metadata & Catalog
- discover database metadata
- maintain canonical catalog
- store schemas, tables, columns
- track relationships (PK/FK)

### Governance
- classify data sensitivity
- define transformation policies
- evaluate policy coverage
- enforce governance before delivery

### Extraction
- build extraction plans
- preview extraction plans
- execute extraction jobs
- apply transformations
- materialize artifacts

### Artifact Management
- store extraction artifacts
- track artifact lifecycle
- manage retention and cleanup
- compute artifact metadata (checksum, size, row count)

### Delivery
- deliver sanitized datasets to target environments
- support baseline publishing
- support artifact-based publishing

### Traceability
- lineage across:
  - extraction
  - artifacts
  - publish jobs
  - baselines
- strong audit logging

---

# Data Protection

The platform must support these transformation types:

- deterministic pseudonymization
- irreversible masking
- reversible tokenization (token vault)
- hashing
- synthetic replacement
- generalization

Reversible transformations must be isolated behind a **token vault service** with strict RBAC.

---

# Hard Constraints

- On-prem only
- Single organization only
- Same DB engine for source and target in first implementation
- Prefer reading from replica/snapshot rather than production primary
- Full relational consistency must be preserved
- Strong governance, audit, lineage, and validation are mandatory

---

# Architecture Principles

### Separation of Planes

Control plane:
- catalog
- governance
- policies
- lineage
- audit
- planning

Data plane:
- extraction
- transformation
- artifact generation
- delivery

---

### Technology Independence

The core domain must remain technology-agnostic.

Vendor-specific behavior must live in adapters.

Examples:
- PostgreSQL metadata discovery adapter
- PostgreSQL extraction adapter
- PostgreSQL publish adapter

---

### Canonical Metadata Model

The platform must define a canonical metadata model independent from the physical database.

---

### API-First Backend

The backend must expose APIs for all platform operations.

The web UI is a thin layer over these APIs.

---

### Operational Safety

- workflows must be asynchronous jobs
- artifacts must be tracked and lifecycle-managed
- publish operations must be auditable
- lineage must connect all major entities

---

# Working Order for Agents

When implementing changes:

1. Inspect the repository
2. Identify what is implemented vs stubbed
3. Propose a short execution plan
4. Update docs if architecture changes
5. Define domain model and interfaces
6. Implement minimal realistic behavior
7. Add or update tests
8. Summarize assumptions, risks, and TODOs

---

# Implementation Guidelines

- keep workflows explicit (refresh, extraction, publish, artifact lifecycle)
- avoid merging distinct workflows prematurely
- prefer composition over duplication
- keep tests realistic
- do not introduce vendor logic into the domain
- keep artifacts, lineage, and governance as first-class concepts

---

# Product Direction

The platform evolves in this order:

1. metadata discovery
2. governance and policy coverage
3. extraction planning and execution
4. artifact lifecycle
5. artifact-based delivery
6. baseline management
7. operational hardening

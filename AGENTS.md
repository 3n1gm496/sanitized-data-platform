# AGENTS.md

## Mission
Build an internal on-prem self-service sanitized data delivery platform that provisions policy-governed copies of production data into non-production environments.

## Product scope
This repository is for a platform that delivers sanitized data to:
- DEV
- TEST
- COLLAUDO

Production remains the only environment with real data.

## Hard constraints
- On-prem only
- Single organization only
- Self-service for internal users
- Source and target must use the same database engine in the first implementation
- Prefer reading from replica, snapshot, restore point, or equivalent safe source over primary production
- Default mode is full sanitized clone
- Architecture must support future subset and scenario-based datasets
- Full data consistency across related tables and domains is mandatory
- Support:
  - deterministic pseudonymization
  - irreversible masking
  - reversible tokenization
  - hashing
  - synthetic replacement
  - generalization
- Reversibility must be selective and isolated behind a token-vault style service with strict RBAC
- Strong governance, audit, lineage, and validation are mandatory
- Prefer agentless integrations where realistically possible
- Optimize for fast publish using precomputed sanitized baselines
- Default UX must be simple:
  1. choose system
  2. choose target environment
  3. choose dataset profile
  4. run

## Architecture rules
- This is not a live proxy to production
- This is not a generic ETL product
- This is a sanitized data delivery platform
- Separate control plane and data plane
- Keep the core technology-agnostic
- Use adapters/plugins for vendor-specific behavior
- Define a canonical metadata model independent from physical DB details
- Prefer API-first backend design with a simple web UI on top
- Design for large datasets
- Do not hardcode vendor-specific logic into the core domain

## Working order
1. inspect the existing repository
2. propose a short execution plan
3. update docs first if the change affects architecture or behavior
4. define domain model and interfaces
5. scaffold code
6. implement minimal realistic behavior
7. add or update tests
8. summarize assumptions, risks, and TODOs

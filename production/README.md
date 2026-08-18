# Production Platform Reference

The chapter directories remain useful as learning and component examples. This directory is the production inversion of the book: one enterprise platform architecture in which the chapter concerns become governed capabilities with shared contracts, admission, evidence, and lifecycle management.

## Production target

The target is not a larger Kubernetes demo. It is an enterprise platform operating system with four architectural domains (business, application, data, technology), explicit architecture governance, policy-enforced state transitions, supply-chain provenance, SRE and FinOps controls, resilience automation, and bounded AI participation.

The architecture follows the TOGAF ADM lifecycle for governance and traceability. It uses open semantic vocabularies for interoperable meaning and treats concrete tools such as Backstage, GitHub Actions, Flux, Crossplane, OPA, OpenTelemetry, Prometheus, and Kubernetes as replaceable implementation adapters.

## Canonical flow

```text
observe -> select -> construct -> request -> authenticate -> authorize
        -> validate -> policy -> risk -> plan -> actuate -> receipt -> replay
```

Interfaces do not receive ambient production authority. Portal, CLI, API, MCP, A2A, GitOps and AI agents can construct or submit intents. A state-changing adapter must consume an admitted intent and emit evidence suitable for replay and audit.

## Architecture surfaces

- `architecture/enterprise.yaml` — TOGAF-oriented enterprise architecture, operating model, principles, domains, topology, and governance.
- `architecture/chapter-capability-map.yaml` — explicit backward mapping from all 14 chapters to production capabilities and evidence.
- `ontology/platform.ttl` — canonical semantic model using public vocabularies plus platform-specific terms.
- `contracts/platform.yaml` — platform product contract across portal, CLI, API, events, MCP, A2A, GitOps, reliability, FinOps, supply chain, and AI.
- `governance/controls.yaml` — architecture, security, software supply chain, SRE, DORA, FinOps, runtime, data, and AI control families.
- `runtime/admission.py` — deterministic admission kernel that cannot actuate external systems.
- `runtime/receipt.schema.json` — machine-readable receipt envelope for admitted/refused/blocked work and later actuation evidence.
- `verify.py` — static closure verifier. Passing it proves repository architecture closure only, not a live cloud deployment.

## Backward chapter integration

The production system deliberately collapses chapter silos:

1. Product, principles, architecture governance, ownership, and release governance.
2. Runtime, GitOps, mesh, tenancy, infrastructure-as-code.
3. Identity, least privilege, policy enforcement, zero trust, TLS.
4. Unified telemetry and deployment observability.
5. DevEx journeys and DORA evidence.
6. Catalog/discovery as an experience layer, not platform authority.
7. API-first tenant/team/project onboarding with idempotent evidence.
8. Delivery as a composable service with provenance and rollback.
9. Infrastructure claims/compositions behind governance.
10. Starter kits as generated projections with drift/upgrade control.
11. Policy as executable admission and exception lifecycle.
12. FinOps, capacity, scaling and unit economics.
13. SLOs, error budgets, chaos, backup, restore and DR proof.
14. AI for observation, diagnosis, planning and intent generation without ambient actuation rights.

## Verification

Run:

```bash
python3 production/verify.py
python3 -m unittest production.tests.test_production -v
```

A green result is `ALIVE` only for the static production architecture capsule represented by these files. Kubernetes clusters, cloud resources, identity providers, registries, policy engines, telemetry backends, and AI services require separate runtime receipts before they can be called production-alive.

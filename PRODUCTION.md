# From Handbook to Production Platform

The original repository is organized by chapter. The production implementation is organized by enterprise capability.

Start at [`production/README.md`](production/README.md).

The production layer adds:

- TOGAF-aligned enterprise architecture and governance
- a complete 14-chapter capability/evidence map
- a canonical semantic ontology based on public vocabularies plus platform terms
- one platform product contract across portal, CLI, API, events, MCP, A2A and GitOps
- cross-cutting security, supply-chain, SRE, DORA, FinOps, data and AI controls
- an admission kernel with explicit refusal for unsafe destructive work
- a receipt schema separating admission from actual actuation
- repository-level verification that refuses to equate static configuration with a live production system

The chapter folders are retained as implementation examples and migration inputs. Over time, production adapters should be generated or reconciled from the canonical architecture and contracts rather than maintained as independent sources of truth.

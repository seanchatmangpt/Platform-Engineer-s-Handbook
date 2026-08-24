# Chapter 14: Production AI-Augmented Platform Operations

Chapter 14 is wired to observed platform state. The executable paths do not fabricate telemetry, incidents, LLM responses, approvals, or actuation results. Missing credentials, unavailable dependencies, unreachable services, and denied changes fail closed.

## Runtime boundary

The AI layer may **observe, diagnose, plan, and construct an intent**. It does not receive Kubernetes mutation credentials or direct cloud/shell authority. Consequential work is submitted to the production platform intent API and reaches an actuator only after admission through BRCE.

```text
Kubernetes + Prometheus + Alertmanager + platform docs
                    │
                    ▼
       observe → diagnose → plan
                    │
                    ▼
             construct intent
                    │
                    ▼
      admission → BRCE DO → receipt
```

## Required configuration

Install the runtime dependencies:

```bash
cd Ch14
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Configure only the services needed by the command being run. Secrets should come from the deployment secret store, workload identity, or the Chapter 1 vault workflow; do not commit secret values.

| Variable | Used by | Requirement |
|---|---|---|
| `ANTHROPIC_API_KEY` | RAG, incident synthesis | required for LLM calls |
| `ANTHROPIC_MODEL` | RAG, incident synthesis | required model identity |
| `PROMETHEUS_URL` | incident analysis | Prometheus HTTPS endpoint |
| `PROMETHEUS_TOKEN` | incident analysis | optional bearer token when the endpoint requires it |
| `ALERTMANAGER_URL` | alert correlation | Alertmanager HTTPS endpoint |
| `ALERTMANAGER_TOKEN` | alert correlation | optional bearer token |
| `KUBECONFIG` | Kubernetes observation/actuation | used when not running with in-cluster identity |
| `PLATFORM_BROKER_URL` | state-changing intent submission | production intent API base URL |
| `PLATFORM_BROKER_TOKEN` | state-changing intent submission | bearer token for the intent API |
| `AI_AUDIT_LOG` | agents/runbooks | durable JSONL audit path |
| `GITHUB_ACTUATOR_TOKEN` | GitHub desired-state updates | token scoped to the managed repository |
| `RUNBOOK_NOTIFICATION_WEBHOOK` | runbook notifications | HTTPS notification endpoint |
| `PLATFORM_CA_FILE` | outbound HTTPS | optional custom CA bundle |
| `RAG_CHROMA_PATH` | RAG | persistent Chroma path; defaults to `.platform-rag/chroma` |
| `RAG_EMBEDDING_MODEL` | RAG | sentence-transformers model identity |

Kubernetes configuration first attempts in-cluster service-account identity and then falls back to `KUBECONFIG`. Failure to authenticate is a runtime error, not an alternate execution mode.

## Real RAG

`platform_chatbot/rag_pipeline.py` uses a persistent Chroma collection, sentence-transformers embeddings, actual repository/platform documents, and Anthropic synthesis.

```bash
export ANTHROPIC_API_KEY='...'
export ANTHROPIC_MODEL='...'
python3 platform_chatbot/rag_pipeline.py \
  --docs ../production ../Ch02 ../Ch03 ../Ch13 \
  --query 'What evidence is required before a production promotion?'
```

The command refuses nonexistent document roots, unavailable vector/embedding dependencies, and missing LLM configuration.

## Live incident triage

`platform_chatbot/incident_triage.py` and `incident-agent.py` collect pod state, Kubernetes events/logs, and Prometheus measurements from the named workload. Anthropic receives the observed evidence and returns structured diagnosis. Any proposed mutation remains an intent until an explicit approval reference is supplied.

Example request file:

```json
{
  "namespace": "payments",
  "pod": "payments-api-7d9b8f6c9-x1y2z",
  "severity": "critical",
  "error_rate_query": "sum(rate(http_requests_total{namespace=\"payments\",status=~\"5..\"}[5m]))"
}
```

```bash
export PROMETHEUS_URL='https://prometheus.example.internal'
export ANTHROPIC_API_KEY='...'
export ANTHROPIC_MODEL='...'
python3 platform_chatbot/incident_triage.py incident.json
python3 incident-agent.py incident.json
```

To submit an approved remediation, configure `PLATFORM_BROKER_URL`, `PLATFORM_BROKER_TOKEN`, and `AI_AUDIT_LOG`, then use the approval option exposed by the command. The broker—not the model—owns DO authority.

## Multi-agent operations

`agents/multi_agent_system.py` uses the same live Kubernetes/Prometheus clients. Investigation is read-only. Planning constructs reversible steps. Execution submits approved state-changing steps to BRCE and reports the broker response; it never returns a fabricated completion.

```bash
python3 agents/multi_agent_system.py incident.json
```

## Alert correlation

`alert-correlator.py` reads active alerts from Alertmanager and correlates them by time, metric, source, namespace, and service labels.

```bash
export ALERTMANAGER_URL='https://alertmanager.example.internal'
python3 alert-correlator.py
```

## Runbook execution

`runbook-automator.py` has two execution classes:

- diagnostics: an allowlisted, argument-vector subprocess runner for read-only commands such as `kubectl get`, `kubectl logs`, `helm status`, and `systemctl status`; shell metacharacters are rejected;
- actions: never executed as local shell commands. They require approval, subject identity, rollback metadata, a typed action name, and JSON `Parameters`, then become BRCE intents.

The production actuator accepts the bounded action set `rollout_restart`, `patch_container_resources`, and `github_upsert_file`. Unsupported action names are refused.

```bash
python3 runbook-automator.py /srv/runbooks/database-recovery.md --approvals /srv/approvals/incident.json
```

## Observed impact metrics

`measure-ai-impact.py` accepts actual JSON/NDJSON incident exports or an incident-management HTTP endpoint. It validates monotonic timestamps and requires both AI-assisted and non-AI observations before computing comparisons.

```bash
python3 measure-ai-impact.py /srv/evidence/incidents.ndjson
```

## Production intent service

The `production/` ggen project manufactures the runtime used by Chapter 14 and the other handbook capabilities:

- `runtime/generated_platform.py` — capability registry, admission boundary, BRCE broker, and typed Kubernetes/GitHub production actuator;
- `runtime/persistent_ledger.py` — SQLite receipt ledger with WAL/FULL durability and replay verification;
- `runtime/platform_api.py` — authenticated `/v1/intents` and `/healthz` service;
- `runtime/dfcm_generated.py` — marketplace-generated DfCM/BRCE law and BLAKE3 receipt implementation.

The production API requires `PLATFORM_RECEIPT_DB`, `PLATFORM_SOURCE_IDENTITY`, `PLATFORM_BASE_IDENTITY`, `PLATFORM_ENVIRONMENT_IDENTITY`, `PLATFORM_AUTHORITY`, and `PLATFORM_API_TOKEN`. TLS should terminate at the service mesh/ingress; outbound GitHub traffic uses TLS directly.

These files are generated consequences. Change ontology/templates and rerun `production/ggen/manufacture.sh`; do not hand-edit generated output.

## Verification

```bash
python3 test-ai-agents.py -v
python3 ../production/verify.py
```

Production CI additionally installs the digest-pinned ggen toolchain, manufactures the consequences twice, proves deterministic code/topology replay, validates provider construction receipts, and runs the production tests.

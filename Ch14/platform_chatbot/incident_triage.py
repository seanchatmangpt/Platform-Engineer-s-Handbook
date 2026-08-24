#!/usr/bin/env python3
"""Live multi-signal incident triage for Kubernetes workloads.

Signals come from Kubernetes and Prometheus, and Anthropic is required for synthesis. Configuration failures are explicit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime_clients import AnthropicRuntime, KubernetesRuntime, PrometheusClient


@dataclass(frozen=True)
class SignalData:
    signal_type: str
    severity: str
    value: float
    timestamp: str
    source: str
    details: Dict[str, Any]


@dataclass(frozen=True)
class IncidentAnalysis:
    incident_id: str
    title: str
    severity: str
    root_cause: str
    confidence_score: float
    affected_components: List[str]
    timeline: List[str]
    related_signals: List[SignalData]
    remediation_intent: Dict[str, Any]


class IncidentTriageAgent:
    def __init__(self):
        self.k8s = KubernetesRuntime()
        self.prom = PrometheusClient()
        self.llm = AnthropicRuntime()

    def collect(self, request: Dict[str, Any]) -> List[SignalData]:
        namespace = str(request["namespace"])
        pod = str(request["pod"])
        now = datetime.now(timezone.utc).isoformat()
        snapshot = self.k8s.pod_snapshot(namespace, pod)
        events = self.k8s.recent_events(namespace, object_name=pod)
        logs = self.k8s.pod_logs(namespace, pod, tail_lines=int(request.get("tail_lines", 200)))
        error_rate = self.prom.scalar(str(request.get("error_rate_query") or f'sum(rate(http_requests_total{{namespace="{namespace}",pod="{pod}",status=~"5.."}}[5m])) / clamp_min(sum(rate(http_requests_total{{namespace="{namespace}",pod="{pod}"}}[5m])), 1e-9)'), default=0.0)
        restart_delta = self.prom.scalar(f'sum(increase(kube_pod_container_status_restarts_total{{namespace="{namespace}",pod="{pod}"}}[15m]))', default=0.0)
        return [
            SignalData("pod_state", str(request.get("severity", "medium")), 1.0, now, "kubernetes", snapshot),
            SignalData("recent_events", str(request.get("severity", "medium")), float(len(events)), now, "kubernetes", {"events": events}),
            SignalData("error_rate", str(request.get("severity", "medium")), float(error_rate), now, "prometheus", {"query": "error_rate", "value": error_rate}),
            SignalData("restart_delta_15m", str(request.get("severity", "medium")), float(restart_delta), now, "prometheus", {"value": restart_delta}),
            SignalData("log_tail", str(request.get("severity", "medium")), 1.0, now, "kubernetes", {"text": logs[-12000:]}),
        ]

    def triage(self, request: Dict[str, Any]) -> IncidentAnalysis:
        signals = self.collect(request)
        namespace = str(request["namespace"])
        pod = str(request["pod"])
        prompt = (
            "Analyze these observed Kubernetes incident signals. Return strict JSON with keys: "
            "root_cause, confidence, affected_components, remediation_intent. "
            "remediation_intent must contain capability_id, subject, action, parameters, rollback. "
            "Do not claim any remediation executed.\n\n"
            f"REQUEST={json.dumps(request, sort_keys=True)}\n"
            f"SIGNALS={json.dumps([asdict(s) for s in signals], default=str, sort_keys=True)}"
        )
        raw = self.llm.answer(prompt, max_tokens=1600, temperature=0.0)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM triage response is not JSON: {raw[:1000]}") from exc
        confidence = float(parsed.get("confidence", 0.0))
        if not 0 <= confidence <= 1:
            raise RuntimeError(f"invalid confidence: {confidence}")
        incident_seed = f"{request.get('alert','')}|{namespace}|{pod}|{signals[0].timestamp}"
        incident_id = "INC-" + hashlib.sha256(incident_seed.encode("utf-8")).hexdigest()[:12].upper()
        timeline = [f"{signal.timestamp} {signal.source}:{signal.signal_type}={signal.value}" for signal in signals]
        remediation = parsed.get("remediation_intent")
        if not isinstance(remediation, dict):
            raise RuntimeError("triage response omitted remediation_intent")
        return IncidentAnalysis(
            incident_id=incident_id,
            title=str(request.get("alert") or f"Incident for {namespace}/{pod}"),
            severity=str(request.get("severity", "medium")),
            root_cause=str(parsed.get("root_cause", "")).strip(),
            confidence_score=confidence,
            affected_components=[str(item) for item in parsed.get("affected_components", [])],
            timeline=timeline,
            related_signals=signals,
            remediation_intent=remediation,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Triage a live Kubernetes workload incident")
    parser.add_argument("request", help="JSON file with alert, namespace, pod, optional deployment")
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    print(json.dumps(asdict(IncidentTriageAgent().triage(request)), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

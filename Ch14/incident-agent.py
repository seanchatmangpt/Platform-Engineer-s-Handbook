#!/usr/bin/env python3
"""Production incident triage/diagnosis/remediation intent agent.

Observations are collected from live Kubernetes and Prometheus. The agent never
executes state changes directly; approved remediation is submitted to BRCE.
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from runtime_clients import AnthropicRuntime, BRCEIntentClient, JsonlAuditSink, KubernetesRuntime, PrometheusClient


class SeverityLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class IncidentTarget:
    namespace: str
    pod: str
    deployment: Optional[str] = None


@dataclass(frozen=True)
class DiagnosisResult:
    root_cause: str
    confidence: float
    evidence: List[Dict[str, Any]]
    remediation: Dict[str, Any]


class IncidentAgent:
    def __init__(self):
        self.k8s = KubernetesRuntime()
        self.prom = PrometheusClient()
        self.llm = AnthropicRuntime()
        self.audit = JsonlAuditSink()

    def _metrics(self, target: IncidentTarget) -> Dict[str, float]:
        ns = target.namespace.replace('"', '')
        pod = target.pod.replace('"', '')
        return {
            "cpu_cores": self.prom.scalar(f'sum(rate(container_cpu_usage_seconds_total{{namespace="{ns}",pod="{pod}",container!=""}}[5m]))', default=0.0),
            "memory_bytes": self.prom.scalar(f'sum(container_memory_working_set_bytes{{namespace="{ns}",pod="{pod}",container!=""}})', default=0.0),
            "restart_delta_15m": self.prom.scalar(f'sum(increase(kube_pod_container_status_restarts_total{{namespace="{ns}",pod="{pod}"}}[15m]))', default=0.0),
        }

    def diagnose(self, alert: str, severity: SeverityLevel, target: IncidentTarget) -> DiagnosisResult:
        pod = self.k8s.pod_snapshot(target.namespace, target.pod)
        logs = self.k8s.pod_logs(target.namespace, target.pod, tail_lines=200)
        events = self.k8s.recent_events(target.namespace, object_name=target.pod)
        metrics = self._metrics(target)
        deployment = self.k8s.deployment_snapshot(target.namespace, target.deployment) if target.deployment else None
        evidence = [
            {"kind": "kubernetes.pod", "value": pod},
            {"kind": "kubernetes.events", "value": events},
            {"kind": "prometheus.metrics", "value": metrics},
            {"kind": "kubernetes.logs", "value": logs[-12000:]},
        ]
        if deployment is not None:
            evidence.append({"kind": "kubernetes.deployment", "value": deployment})
        prompt = (
            "You are an incident diagnosis component. Analyze only the observed evidence below. "
            "Return JSON with keys root_cause, confidence (0..1), and remediation. "
            "remediation must contain capability_id, subject, action, parameters, rollback. "
            "Do not claim an action was executed. Prefer reversible actions.\n\n"
            f"ALERT: {alert}\nSEVERITY: {severity.value}\n"
            f"TARGET: {json.dumps(asdict(target), sort_keys=True)}\n"
            f"EVIDENCE: {json.dumps(evidence, default=str, sort_keys=True)}"
        )
        raw = self.llm.answer(prompt, max_tokens=1800, temperature=0.0)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM diagnosis was not valid JSON: {raw[:1000]}") from exc
        confidence = float(parsed.get("confidence", 0.0))
        if not 0.0 <= confidence <= 1.0:
            raise RuntimeError(f"invalid confidence: {confidence}")
        remediation = parsed.get("remediation")
        if not isinstance(remediation, dict):
            raise RuntimeError("diagnosis omitted structured remediation")
        result = DiagnosisResult(root_cause=str(parsed.get("root_cause", "")).strip(), confidence=confidence, evidence=evidence, remediation=remediation)
        self.audit.append({"event": "incident_diagnosis", "alert": alert, "severity": severity.value, "target": asdict(target), "diagnosis": asdict(result), "timestamp_ns": time.time_ns()})
        return result

    def submit_approved_remediation(self, diagnosis: DiagnosisResult, *, approver: str, approval_reference: str) -> Dict[str, Any]:
        if not approver.strip() or not approval_reference.strip():
            raise ValueError("approver and approval_reference are required")
        remediation = diagnosis.remediation
        capability_id = str(remediation.get("capability_id") or "ai-augmentation")
        subject = str(remediation.get("subject") or "").strip()
        if not subject:
            raise RuntimeError("remediation has no subject")
        payload = {
            "action": remediation.get("action"),
            "parameters": remediation.get("parameters", {}),
            "rollback": remediation.get("rollback"),
            "diagnosis": diagnosis.root_cause,
            "confidence": diagnosis.confidence,
            "approval": {"approver": approver, "reference": approval_reference},
            "source": "Ch14/incident-agent.py",
        }
        intent_id = f"inc-remediation-{uuid.uuid4().hex}"
        receipt = BRCEIntentClient().submit(capability_id=capability_id, intent_id=intent_id, subject=subject, payload=payload)
        self.audit.append({"event": "remediation_intent_submitted", "intent_id": intent_id, "subject": subject, "broker_response": receipt, "timestamp_ns": time.time_ns()})
        return receipt


def _load_request(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose a live Kubernetes incident")
    parser.add_argument("request", help="JSON request containing alert, severity, namespace, pod, optional deployment")
    parser.add_argument("--approve", action="store_true", help="Submit the generated remediation intent to BRCE")
    parser.add_argument("--approver")
    parser.add_argument("--approval-reference")
    args = parser.parse_args()
    request = _load_request(args.request)
    target = IncidentTarget(request["namespace"], request["pod"], request.get("deployment"))
    agent = IncidentAgent()
    diagnosis = agent.diagnose(str(request["alert"]), SeverityLevel(str(request.get("severity", "medium")).lower()), target)
    output: Dict[str, Any] = {"diagnosis": asdict(diagnosis)}
    if args.approve:
        output["broker"] = agent.submit_approved_remediation(diagnosis, approver=args.approver or "", approval_reference=args.approval_reference or "")
    print(json.dumps(output, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

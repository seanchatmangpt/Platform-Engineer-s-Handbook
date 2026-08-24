#!/usr/bin/env python3
"""Production multi-agent Kubernetes operations pipeline.

Investigation is live/read-only. Planning produces structured intents. Execution
submits approved state changes to BRCE; it never fabricates completion results.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime_clients import BRCEIntentClient, JsonlAuditSink, KubernetesRuntime, PrometheusClient


@dataclass(frozen=True)
class Investigation:
    issue_type: str
    subject: str
    evidence: Dict[str, Any]
    confidence: float


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    capability_id: str
    subject: str
    action: str
    parameters: Dict[str, Any]
    rollback: Dict[str, Any]
    state_changing: bool
    requires_approval: bool


class InvestigationAgent:
    def __init__(self):
        self.k8s = KubernetesRuntime()
        self.prom = PrometheusClient()

    def execute(self, task: Dict[str, Any]) -> Investigation:
        namespace = str(task["namespace"])
        pod = str(task["pod"])
        snapshot = self.k8s.pod_snapshot(namespace, pod)
        events = self.k8s.recent_events(namespace, object_name=pod)
        logs = self.k8s.pod_logs(namespace, pod, tail_lines=int(task.get("tail_lines", 200)))
        restart_delta = self.prom.scalar(f'sum(increase(kube_pod_container_status_restarts_total{{namespace="{namespace}",pod="{pod}"}}[15m]))', default=0.0)
        oom = any(item.get("last_terminated_reason") == "OOMKilled" or item.get("terminated_reason") == "OOMKilled" for item in snapshot.get("containers", []))
        confidence = 0.97 if oom else (0.90 if restart_delta > 0 else 0.75)
        return Investigation(issue_type=str(task.get("issue_type", "kubernetes_incident")), subject=f"k8s://{namespace}/pod/{pod}", evidence={"pod": snapshot, "events": events, "logs": logs[-12000:], "restart_delta_15m": restart_delta, "oom_killed": oom}, confidence=confidence)


class PlanningAgent:
    def execute(self, investigation: Investigation, task: Dict[str, Any]) -> List[PlanStep]:
        namespace = str(task["namespace"])
        deployment = str(task.get("deployment") or "").strip()
        if investigation.evidence.get("oom_killed"):
            if not deployment:
                raise RuntimeError("OOM remediation requires deployment in task")
            memory = str(task.get("target_memory") or "512Mi")
            return [PlanStep(step_id=f"step-{uuid.uuid4().hex[:12]}", capability_id="runtime-gitops", subject=f"k8s://{namespace}/deployment/{deployment}", action="patch_container_resources", parameters={"namespace": namespace, "deployment": deployment, "memory_request": memory}, rollback={"strategy": "rollout_undo", "namespace": namespace, "deployment": deployment}, state_changing=True, requires_approval=True)]
        if float(investigation.evidence.get("restart_delta_15m", 0.0)) > 0:
            if not deployment:
                raise RuntimeError("restart remediation requires deployment in task")
            return [PlanStep(step_id=f"step-{uuid.uuid4().hex[:12]}", capability_id="runtime-gitops", subject=f"k8s://{namespace}/deployment/{deployment}", action="rollout_restart", parameters={"namespace": namespace, "deployment": deployment}, rollback={"strategy": "rollout_undo", "namespace": namespace, "deployment": deployment}, state_changing=True, requires_approval=True)]
        return [PlanStep(step_id=f"step-{uuid.uuid4().hex[:12]}", capability_id="observability", subject=investigation.subject, action="continue_observation", parameters={"window_seconds": int(task.get("observation_window_seconds", 300))}, rollback={}, state_changing=False, requires_approval=False)]


class ExecutionAgent:
    def __init__(self):
        self.audit = JsonlAuditSink()

    def execute(self, steps: List[PlanStep], approvals: Dict[str, Dict[str, str]]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for step in steps:
            if not step.state_changing:
                result = {"step_id": step.step_id, "status": "observed", "action": step.action}
                self.audit.append({"event": "read_only_step", "step": asdict(step), "timestamp_ns": time.time_ns()})
                results.append(result)
                continue
            approval = approvals.get(step.step_id)
            if step.requires_approval and not approval:
                results.append({"step_id": step.step_id, "status": "waiting_for_approval"})
                continue
            if approval and (not approval.get("approver") or not approval.get("reference")):
                raise RuntimeError(f"approval for {step.step_id} requires approver and reference")
            intent_id = f"agent-{uuid.uuid4().hex}"
            payload = {"action": step.action, "parameters": step.parameters, "rollback": step.rollback, "approval": approval, "source": "Ch14/agents/multi_agent_system.py"}
            broker_response = BRCEIntentClient().submit(capability_id=step.capability_id, intent_id=intent_id, subject=step.subject, payload=payload)
            result = {"step_id": step.step_id, "status": "submitted_to_brce", "intent_id": intent_id, "broker": broker_response}
            self.audit.append({"event": "brce_submission", "step": asdict(step), "result": result, "timestamp_ns": time.time_ns()})
            results.append(result)
        return results


class SupervisorAgent:
    def __init__(self):
        self.investigation = InvestigationAgent()
        self.planning = PlanningAgent()
        self.execution = ExecutionAgent()

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        investigation = self.investigation.execute(task)
        plan = self.planning.execute(investigation, task)
        approvals = task.get("approvals") or {}
        if not isinstance(approvals, dict):
            raise ValueError("approvals must be an object keyed by step_id")
        results = self.execution.execute(plan, approvals)
        return {"workflow_id": f"wf-{uuid.uuid4().hex}", "investigation": asdict(investigation), "plan": [asdict(step) for step in plan], "execution": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the live Kubernetes multi-agent workflow")
    parser.add_argument("request", help="JSON task with namespace, pod, optional deployment and approvals")
    args = parser.parse_args()
    task = json.loads(Path(args.request).read_text(encoding="utf-8"))
    result = SupervisorAgent().execute(task)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

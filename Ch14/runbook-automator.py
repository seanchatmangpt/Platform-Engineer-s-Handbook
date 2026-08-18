#!/usr/bin/env python3
"""Production runbook executor.

Read-only diagnostics execute locally without a shell. State-changing steps are
never executed directly; approved steps become BRCE intents. Notification steps
use a configured webhook. No simulated success paths exist.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import time
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from runtime_clients import BRCEIntentClient, JsonlAuditSink, require_env


class StepType(str, Enum):
    DIAGNOSTIC = "diagnostic"
    ACTION = "action"
    APPROVAL = "approval"
    DECISION = "decision"
    NOTIFICATION = "notification"


@dataclass(frozen=True)
class RunbookStep:
    step_id: str
    name: str
    step_type: StepType
    command: str
    parameters: Dict[str, object]
    condition: Optional[str]
    requires_approval: bool
    timeout_seconds: int
    success_criteria: str
    rollback_action: Optional[str]
    capability_id: str = "runtime-gitops"
    subject: str = ""


class RunbookParser:
    def parse_markdown(self, content: str) -> Tuple[str, List[RunbookStep]]:
        lines = content.splitlines()
        title = next((line.split(":", 1)[1].strip() for line in lines if line.startswith("# Runbook:")), "Unnamed Runbook")
        raw_steps: List[Dict[str, object]] = []
        current: Optional[Dict[str, object]] = None
        counter = 1
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("## Step"):
                if current:
                    raw_steps.append(current)
                current = {"step_id": f"step-{counter}", "name": stripped[2:].strip(), "step_type": StepType.DIAGNOSTIC, "command": "", "parameters": {}, "condition": None, "requires_approval": False, "timeout_seconds": 300, "success_criteria": "exit_code=0", "rollback_action": None, "capability_id": "runtime-gitops", "subject": ""}
                counter += 1
                continue
            if current is None or ":" not in stripped:
                continue
            key, value = (part.strip() for part in stripped.split(":", 1))
            lower = key.lower()
            if lower == "type":
                current["step_type"] = StepType(value.lower())
            elif lower == "command":
                current["command"] = value
            elif lower == "parameters":
                parsed = json.loads(value)
                if not isinstance(parsed, dict):
                    raise ValueError("Parameters: must be a JSON object")
                current["parameters"] = parsed
            elif lower == "condition":
                current["condition"] = value
            elif lower == "approvalrequired":
                current["requires_approval"] = value.lower() == "true"
            elif lower == "timeout":
                current["timeout_seconds"] = int(value)
            elif lower == "success":
                current["success_criteria"] = value
            elif lower == "rollback":
                current["rollback_action"] = value
            elif lower == "capability":
                current["capability_id"] = value
            elif lower == "subject":
                current["subject"] = value
        if current:
            raw_steps.append(current)
        steps = [RunbookStep(**row) for row in raw_steps]
        if not steps:
            raise ValueError("runbook contains no steps")
        return title, steps


class SafetyValidator:
    READ_ONLY = {
        "kubectl": {"get", "describe", "logs", "top", "auth", "version", "api-resources", "api-versions"},
        "helm": {"list", "status", "history", "get", "version"},
        "systemctl": {"status", "show", "is-active", "is-enabled"},
        "journalctl": None, "df": None, "ps": None, "ss": None, "dig": None, "nslookup": None,
    }

    @classmethod
    def diagnostic_argv(cls, command: str) -> List[str]:
        argv = shlex.split(command)
        if not argv:
            raise ValueError("empty diagnostic command")
        executable = Path(argv[0]).name
        allowed_verbs = cls.READ_ONLY.get(executable)
        if executable not in cls.READ_ONLY:
            raise PermissionError(f"diagnostic executable not allowlisted: {executable}")
        if allowed_verbs is not None and (len(argv) < 2 or argv[1] not in allowed_verbs):
            raise PermissionError(f"diagnostic verb not allowlisted: {command}")
        if any(token in command for token in (";", "&&", "||", "`", "$(", ">", "<")):
            raise PermissionError("shell metacharacters are forbidden")
        return argv

    @staticmethod
    def validate_action(step: RunbookStep) -> None:
        if not step.requires_approval:
            raise PermissionError("state-changing runbook actions require explicit approval")
        if not step.subject.strip():
            raise ValueError("state-changing step requires Subject:")
        if not step.rollback_action:
            raise ValueError("state-changing step requires Rollback:")


class RunbookExecutor:
    def __init__(self):
        self.audit = JsonlAuditSink()

    def execute_step(self, step: RunbookStep, approvals: Dict[str, Dict[str, str]]) -> Dict[str, object]:
        started = time.monotonic()
        if step.step_type == StepType.DIAGNOSTIC:
            argv = SafetyValidator.diagnostic_argv(step.command)
            proc = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=step.timeout_seconds, check=False, env={**os.environ, "LC_ALL": "C"})
            result: Dict[str, object] = {"step_id": step.step_id, "status": "completed" if proc.returncode == 0 else "failed", "exit_code": proc.returncode, "stdout": proc.stdout[-20000:], "stderr": proc.stderr[-10000:], "duration_seconds": round(time.monotonic() - started, 3)}
        elif step.step_type == StepType.ACTION:
            SafetyValidator.validate_action(step)
            approval = approvals.get(step.step_id)
            if not approval:
                return {"step_id": step.step_id, "status": "waiting_for_approval"}
            if not approval.get("approver") or not approval.get("reference"):
                raise ValueError(f"approval for {step.step_id} requires approver and reference")
            intent_id = f"runbook-{uuid.uuid4().hex}"
            response = BRCEIntentClient().submit(capability_id=step.capability_id, intent_id=intent_id, subject=step.subject, payload={"action": step.command, "parameters": step.parameters, "rollback": step.rollback_action, "success_criteria": step.success_criteria, "approval": approval, "source": "Ch14/runbook-automator.py"})
            result = {"step_id": step.step_id, "status": "submitted_to_brce", "intent_id": intent_id, "broker": response}
        elif step.step_type == StepType.NOTIFICATION:
            webhook = require_env("RUNBOOK_NOTIFICATION_WEBHOOK")
            payload = json.dumps({"text": step.command, "step_id": step.step_id}).encode("utf-8")
            request = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=step.timeout_seconds) as response:
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(f"notification webhook returned {response.status}")
            result = {"step_id": step.step_id, "status": "notified"}
        else:
            result = {"step_id": step.step_id, "status": "waiting_for_human", "type": step.step_type.value}
        self.audit.append({"event": "runbook_step", "step": asdict(step), "result": result, "timestamp_ns": time.time_ns()})
        return result

    def execute(self, name: str, steps: List[RunbookStep], approvals: Dict[str, Dict[str, str]]) -> Dict[str, object]:
        results: List[Dict[str, object]] = []
        for step in steps:
            result = self.execute_step(step, approvals)
            results.append(result)
            if result.get("status") in {"failed", "waiting_for_approval", "waiting_for_human"}:
                break
        return {"runbook": name, "execution_id": f"exec-{uuid.uuid4().hex}", "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute a production runbook")
    parser.add_argument("runbook", help="Markdown runbook path")
    parser.add_argument("--approvals", help="JSON file keyed by step_id")
    args = parser.parse_args()
    content = Path(args.runbook).read_text(encoding="utf-8")
    name, steps = RunbookParser().parse_markdown(content)
    approvals = json.loads(Path(args.approvals).read_text(encoding="utf-8")) if args.approvals else {}
    print(json.dumps(RunbookExecutor().execute(name, steps, approvals), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

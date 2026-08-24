#!/usr/bin/env python3
"""Deterministic admission kernel for the production platform reference.

This module intentionally does not execute cloud, shell, Kubernetes, or GitHub actions.
It converts a request into an admission decision and a receipt-shaped record that an
external broker/executor can extend after actual actuation.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import json
from typing import Iterable

TERMINAL = {"ADMITTED", "REFUSED", "BLOCKED"}


@dataclass(frozen=True)
class Intent:
    id: str
    actor: str
    operation: str
    subject_kind: str
    subject_id: str
    subject_digest: str
    idempotency_key: str
    destructive: bool = False
    recovery_proof: str | None = None


@dataclass(frozen=True)
class Decision:
    status: str
    controls: tuple[str, ...]
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in TERMINAL:
            raise ValueError(f"invalid decision status: {self.status}")


def _stable_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + sha256(encoded).hexdigest()


def admit(intent: Intent, required_controls: Iterable[str]) -> Decision:
    reasons: list[str] = []
    controls = tuple(sorted(set(required_controls)))
    if not intent.id or not intent.actor or not intent.operation:
        reasons.append("identity-or-operation-missing")
    if not intent.subject_digest:
        reasons.append("subject-digest-missing")
    if not intent.idempotency_key:
        reasons.append("idempotency-key-missing")
    if intent.destructive and not intent.recovery_proof:
        reasons.append("destructive-change-without-recovery-proof")
    if reasons:
        return Decision("REFUSED", controls, tuple(reasons))
    return Decision("ADMITTED", controls, ())


def pre_actuation_receipt(intent: Intent, decision: Decision) -> dict:
    payload = {
        "receipt_version": 1,
        "subject": {
            "kind": intent.subject_kind,
            "id": intent.subject_id,
            "digest": intent.subject_digest,
        },
        "intent": {
            "id": intent.id,
            "actor": intent.actor,
            "operation": intent.operation,
            "idempotency_key": intent.idempotency_key,
        },
        "decision": {
            "status": decision.status,
            "controls": list(decision.controls),
            "reasons": list(decision.reasons),
        },
        "actuation": {
            "executor": "external-broker-required",
            "status": "NOT_RUN",
            "started_at": None,
            "finished_at": None,
        },
        "evidence": [
            {"type": "intent", "digest": _stable_digest(asdict(intent))},
            {"type": "decision", "digest": _stable_digest(asdict(decision))},
        ],
        "replay": {
            "replay_key": intent.idempotency_key,
            "replay_safe": decision.status != "ADMITTED" or not intent.destructive,
        },
    }
    payload["receipt_id"] = _stable_digest(payload)
    return payload

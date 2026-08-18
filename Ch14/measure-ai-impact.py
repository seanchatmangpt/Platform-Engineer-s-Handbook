#!/usr/bin/env python3
"""Measure AI impact from observed incident records.

Records must come from an observed JSON/NDJSON incident export or an incident-management HTTP endpoint.
"""
from __future__ import annotations

import argparse
import json
import statistics
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, List


@dataclass(frozen=True)
class Incident:
    id: str
    severity: str
    alert_time: datetime
    ack_time: datetime
    diagnosis_time: datetime
    resolution_time: datetime
    ai_assisted: bool


def _dt(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _incident(row: dict[str, Any]) -> Incident:
    required = ["id", "severity", "alert_time", "ack_time", "diagnosis_time", "resolution_time", "ai_assisted"]
    missing = [key for key in required if key not in row]
    if missing:
        raise ValueError(f"incident record missing fields: {missing}")
    incident = Incident(
        id=str(row["id"]),
        severity=str(row["severity"]),
        alert_time=_dt(str(row["alert_time"])),
        ack_time=_dt(str(row["ack_time"])),
        diagnosis_time=_dt(str(row["diagnosis_time"])),
        resolution_time=_dt(str(row["resolution_time"])),
        ai_assisted=bool(row["ai_assisted"]),
    )
    if not (incident.alert_time <= incident.ack_time <= incident.diagnosis_time <= incident.resolution_time):
        raise ValueError(f"non-monotonic incident timeline: {incident.id}")
    return incident


def load_incidents(source: str, token: str | None = None) -> List[Incident]:
    if source.startswith(("https://", "http://")):
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(source, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    else:
        text = Path(source).read_text(encoding="utf-8")
        if source.endswith(".ndjson") or source.endswith(".jsonl"):
            payload = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            payload = json.loads(text)
    if isinstance(payload, dict):
        payload = payload.get("incidents")
    if not isinstance(payload, list):
        raise ValueError("incident source must be a JSON list or an object with an incidents list")
    incidents = [_incident(row) for row in payload]
    if not incidents:
        raise ValueError("incident source contains no records")
    return incidents


def _average(group: Iterable[Incident], start: str, end: str) -> float:
    values = [(getattr(item, end) - getattr(item, start)).total_seconds() / 60.0 for item in group]
    return statistics.mean(values) if values else 0.0


def _comparison(incidents: List[Incident], start: str, end: str) -> dict[str, float | int]:
    ai = [item for item in incidents if item.ai_assisted]
    manual = [item for item in incidents if not item.ai_assisted]
    ai_value = _average(ai, start, end)
    manual_value = _average(manual, start, end)
    improvement = ((manual_value - ai_value) / manual_value * 100.0) if manual_value else 0.0
    return {"ai_minutes": round(ai_value, 2), "manual_minutes": round(manual_value, 2), "improvement_pct": round(improvement, 2), "ai_count": len(ai), "manual_count": len(manual)}


def report(incidents: List[Incident]) -> dict[str, Any]:
    if not any(i.ai_assisted for i in incidents) or not any(not i.ai_assisted for i in incidents):
        raise ValueError("impact comparison requires both AI-assisted and manual incidents")
    return {"incident_count": len(incidents), "mttr": _comparison(incidents, "alert_time", "resolution_time"), "alert_to_ack": _comparison(incidents, "alert_time", "ack_time"), "ack_to_diagnosis": _comparison(incidents, "ack_time", "diagnosis_time")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure AI impact from observed incident records")
    parser.add_argument("source", help="JSON/NDJSON file or HTTPS incident export endpoint")
    parser.add_argument("--token", help="Bearer token for HTTPS source")
    args = parser.parse_args()
    print(json.dumps(report(load_incidents(args.source, args.token)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

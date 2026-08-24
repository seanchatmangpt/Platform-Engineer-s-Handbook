#!/usr/bin/env python3
"""Correlate live Alertmanager alerts into incidents."""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List

from runtime_clients import AlertmanagerClient


@dataclass(frozen=True)
class Alert:
    id: str
    timestamp: float
    alert_type: str
    severity: str
    source: str
    metric: str
    value: float
    threshold: float
    message: str
    labels: Dict[str, str]


@dataclass
class CorrelatedIncident:
    incident_id: str
    severity: str
    created_at: float
    alerts: List[Alert]
    root_cause: str
    correlation_score: float
    suggested_action: str


class AlertCorrelator:
    TIME_WINDOW = 300.0
    SIMILARITY_THRESHOLD = 0.70

    @staticmethod
    def _similarity(a: Alert, b: Alert) -> float:
        score = 0.0
        if a.metric == b.metric:
            score += 0.45
        if a.source == b.source:
            score += 0.30
        if a.labels.get("namespace") and a.labels.get("namespace") == b.labels.get("namespace"):
            score += 0.10
        if a.labels.get("service") and a.labels.get("service") == b.labels.get("service"):
            score += 0.15
        return min(1.0, score)

    def correlate(self, alerts: List[Alert]) -> List[CorrelatedIncident]:
        if not alerts:
            return []
        alerts = sorted(alerts, key=lambda item: item.timestamp)
        clusters: List[List[Alert]] = []
        for alert in alerts:
            placed = False
            for cluster in clusters:
                if alert.timestamp - cluster[-1].timestamp > self.TIME_WINDOW:
                    continue
                if max(self._similarity(alert, existing) for existing in cluster) >= self.SIMILARITY_THRESHOLD:
                    cluster.append(alert)
                    placed = True
                    break
            if not placed:
                clusters.append([alert])
        return [self._incident(cluster) for cluster in clusters]

    def _incident(self, alerts: List[Alert]) -> CorrelatedIncident:
        severity_rank = {"critical": 4, "high": 3, "warning": 2, "medium": 2, "info": 1, "low": 1}
        severity = max(alerts, key=lambda item: severity_rank.get(item.severity.lower(), 0)).severity
        pair_scores = [self._similarity(a, b) for i, a in enumerate(alerts) for b in alerts[i + 1 :]]
        score = sum(pair_scores) / len(pair_scores) if pair_scores else 1.0
        metrics = {}
        sources = {}
        for alert in alerts:
            metrics[alert.metric] = metrics.get(alert.metric, 0) + 1
            sources[alert.source] = sources.get(alert.source, 0) + 1
        dominant_metric = max(metrics, key=metrics.get)
        dominant_source = max(sources, key=sources.get)
        if metrics[dominant_metric] >= max(2, int(len(alerts) * 0.6)):
            root = f"correlated alert concentration on metric {dominant_metric}"
            action = f"investigate capacity/error source for {dominant_metric}"
        else:
            root = f"correlated alert concentration around {dominant_source}"
            action = f"inspect dependency and deployment history for {dominant_source}"
        stable = "|".join(sorted(item.id for item in alerts))
        incident_id = "inc-" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]
        return CorrelatedIncident(incident_id, severity, alerts[0].timestamp, alerts, root, score, action)


def _float_annotation(raw: Dict[str, Any], key: str, default: float) -> float:
    try:
        return float((raw.get("annotations") or {}).get(key, default))
    except (TypeError, ValueError):
        return default


def from_alertmanager(raw: Dict[str, Any]) -> Alert:
    labels = {str(k): str(v) for k, v in (raw.get("labels") or {}).items()}
    annotations = {str(k): str(v) for k, v in (raw.get("annotations") or {}).items()}
    starts_at = str(raw.get("startsAt") or "")
    if not starts_at:
        raise ValueError("Alertmanager alert missing startsAt")
    ts = datetime.fromisoformat(starts_at.replace("Z", "+00:00")).timestamp()
    fingerprint = str(raw.get("fingerprint") or "").strip()
    if not fingerprint:
        fingerprint = hashlib.sha256(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()
    source = labels.get("pod") or labels.get("service") or labels.get("instance") or labels.get("job") or "unknown"
    metric = labels.get("alertname") or labels.get("__name__") or "unknown"
    message = annotations.get("summary") or annotations.get("description") or metric
    return Alert(id=fingerprint, timestamp=ts, alert_type=labels.get("alertname", "alert"), severity=labels.get("severity", "warning"), source=source, metric=metric, value=_float_annotation(raw, "value", 1.0), threshold=_float_annotation(raw, "threshold", 1.0), message=message, labels=labels)


def main() -> int:
    parser = argparse.ArgumentParser(description="Correlate active alerts from a live Alertmanager")
    parser.add_argument("--include-silenced", action="store_true")
    parser.add_argument("--include-inhibited", action="store_true")
    args = parser.parse_args()
    raw = AlertmanagerClient().alerts(active=True, silenced=args.include_silenced, inhibited=args.include_inhibited)
    alerts = [from_alertmanager(item) for item in raw]
    incidents = AlertCorrelator().correlate(alerts)
    print(json.dumps([asdict(item) for item in incidents], indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

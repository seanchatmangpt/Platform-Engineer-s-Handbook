#!/usr/bin/env python3
"""Production clients for Chapter 14.

No fake responses and no silent fallback. Missing credentials, unavailable
backends, or rejected remote calls raise ConfigurationError/RuntimeError.
State-changing work is submitted as an intent to the platform BRCE API.
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, Optional


class ConfigurationError(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"required environment variable is not set: {name}")
    return value


def _ssl_context() -> ssl.SSLContext:
    cafile = os.getenv("PLATFORM_CA_FILE")
    return ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()


def _json_request(method: str, url: str, *, payload: Optional[Dict[str, Any]] = None, bearer_token: Optional[str] = None, timeout: float = 15.0) -> Dict[str, Any]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
            raw = response.read()
            if not raw:
                return {"status_code": response.status}
            parsed = json.loads(raw.decode("utf-8"))
            if isinstance(parsed, dict):
                parsed.setdefault("status_code", response.status)
                return parsed
            return {"status_code": response.status, "data": parsed}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail[:2000]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"request failed for {url}: {exc.reason}") from exc


class PrometheusClient:
    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None):
        self.base_url = (base_url or require_env("PROMETHEUS_URL")).rstrip("/")
        self.token = token if token is not None else os.getenv("PROMETHEUS_TOKEN")

    def query(self, expression: str, *, at: Optional[float] = None) -> list[dict[str, Any]]:
        params = {"query": expression}
        if at is not None:
            params["time"] = str(at)
        result = _json_request("GET", f"{self.base_url}/api/v1/query?{urllib.parse.urlencode(params)}", bearer_token=self.token)
        if result.get("status") != "success":
            raise RuntimeError(f"Prometheus query failed: {result}")
        data = result.get("data", {})
        if data.get("resultType") not in {"vector", "scalar", "string"}:
            raise RuntimeError(f"unsupported Prometheus result type: {data.get('resultType')}")
        return list(data.get("result", []))

    def scalar(self, expression: str, *, default: Optional[float] = None) -> float:
        rows = self.query(expression)
        if not rows:
            if default is None:
                raise RuntimeError(f"Prometheus query returned no samples: {expression}")
            return default
        value = rows[0].get("value")
        if not isinstance(value, list) or len(value) < 2:
            raise RuntimeError(f"Prometheus vector sample missing value: {rows[0]}")
        return float(value[1])


class AlertmanagerClient:
    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None):
        self.base_url = (base_url or require_env("ALERTMANAGER_URL")).rstrip("/")
        self.token = token if token is not None else os.getenv("ALERTMANAGER_TOKEN")

    def alerts(self, *, active: bool = True, silenced: bool = False, inhibited: bool = False) -> list[dict[str, Any]]:
        params = urllib.parse.urlencode({"active": str(active).lower(), "silenced": str(silenced).lower(), "inhibited": str(inhibited).lower()})
        payload = _json_request("GET", f"{self.base_url}/api/v2/alerts?{params}", bearer_token=self.token)
        data = payload.get("data", payload)
        if isinstance(data, list):
            return data
        raise RuntimeError(f"Alertmanager returned unexpected payload: {payload}")


class KubernetesRuntime:
    """Read-only Kubernetes observer used by AI investigation code."""

    def __init__(self):
        try:
            from kubernetes import client, config
        except ImportError as exc:
            raise ConfigurationError("kubernetes package is required for live cluster access") from exc
        try:
            config.load_incluster_config()
        except Exception:
            try:
                config.load_kube_config(config_file=os.getenv("KUBECONFIG"))
            except Exception as exc:
                raise ConfigurationError("no usable in-cluster or kubeconfig Kubernetes identity") from exc
        self.core = client.CoreV1Api()
        self.apps = client.AppsV1Api()
        self.networking = client.NetworkingV1Api()

    @staticmethod
    def _container_state(container_status: Any) -> Dict[str, Any]:
        state = getattr(container_status, "state", None)
        last_state = getattr(container_status, "last_state", None)
        terminated = getattr(last_state, "terminated", None)
        current_terminated = getattr(state, "terminated", None)
        return {
            "name": getattr(container_status, "name", None),
            "ready": bool(getattr(container_status, "ready", False)),
            "restart_count": int(getattr(container_status, "restart_count", 0) or 0),
            "last_terminated_reason": getattr(terminated, "reason", None),
            "last_exit_code": getattr(terminated, "exit_code", None),
            "terminated_reason": getattr(current_terminated, "reason", None),
            "terminated_exit_code": getattr(current_terminated, "exit_code", None),
        }

    def pod_snapshot(self, namespace: str, pod_name: str) -> Dict[str, Any]:
        pod = self.core.read_namespaced_pod(pod_name, namespace)
        statuses = getattr(pod.status, "container_statuses", None) or []
        owners = getattr(pod.metadata, "owner_references", None) or []
        conditions = getattr(pod.status, "conditions", None) or []
        return {
            "namespace": namespace,
            "name": pod_name,
            "phase": getattr(pod.status, "phase", None),
            "node": getattr(pod.spec, "node_name", None),
            "pod_ip": getattr(pod.status, "pod_ip", None),
            "owners": [{"kind": item.kind, "name": item.name, "uid": item.uid} for item in owners],
            "conditions": [{"type": item.type, "status": item.status, "reason": item.reason, "message": item.message} for item in conditions],
            "containers": [self._container_state(item) for item in statuses],
            "labels": dict(getattr(pod.metadata, "labels", None) or {}),
            "annotations": dict(getattr(pod.metadata, "annotations", None) or {}),
        }

    def pod_logs(self, namespace: str, pod_name: str, *, container: Optional[str] = None, tail_lines: int = 200) -> str:
        return self.core.read_namespaced_pod_log(pod_name, namespace, container=container, timestamps=True, tail_lines=tail_lines)

    def recent_events(self, namespace: str, *, object_name: Optional[str] = None) -> list[Dict[str, Any]]:
        selector = f"involvedObject.name={object_name}" if object_name else None
        events = self.core.list_namespaced_event(namespace, field_selector=selector).items
        rows = []
        for event in events:
            timestamp = event.last_timestamp or event.event_time or event.first_timestamp
            rows.append({"reason": event.reason, "message": event.message, "type": event.type, "count": event.count, "timestamp": timestamp.isoformat() if timestamp else None, "object": getattr(event.involved_object, "name", None)})
        rows.sort(key=lambda item: item.get("timestamp") or "")
        return rows[-100:]

    def deployment_snapshot(self, namespace: str, deployment: str) -> Dict[str, Any]:
        obj = self.apps.read_namespaced_deployment(deployment, namespace)
        return {"namespace": namespace, "name": deployment, "generation": obj.metadata.generation, "observed_generation": obj.status.observed_generation, "replicas": obj.status.replicas or 0, "ready_replicas": obj.status.ready_replicas or 0, "available_replicas": obj.status.available_replicas or 0, "updated_replicas": obj.status.updated_replicas or 0, "annotations": dict(obj.metadata.annotations or {})}

    def network_policies(self, namespace: str) -> list[Dict[str, Any]]:
        return [{"name": item.metadata.name, "pod_selector": dict(item.spec.pod_selector.match_labels or {}), "policy_types": list(item.spec.policy_types or [])} for item in self.networking.list_namespaced_network_policy(namespace).items]


class AnthropicRuntime:
    def __init__(self):
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise ConfigurationError("anthropic package is required for live LLM inference") from exc
        self.model = require_env("ANTHROPIC_MODEL")
        self.client = Anthropic(api_key=require_env("ANTHROPIC_API_KEY"))

    def answer(self, prompt: str, *, max_tokens: int = 1200, temperature: float = 0.0) -> str:
        response = self.client.messages.create(model=self.model, max_tokens=max_tokens, temperature=temperature, messages=[{"role": "user", "content": prompt}])
        text = "".join(getattr(block, "text", "") for block in response.content).strip()
        if not text:
            raise RuntimeError("Anthropic returned an empty response")
        return text


class BRCEIntentClient:
    """Submit state-changing intents to the production platform broker."""
    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None):
        self.base_url = (base_url or require_env("PLATFORM_BROKER_URL")).rstrip("/")
        self.token = token if token is not None else require_env("PLATFORM_BROKER_TOKEN")

    def submit(self, *, capability_id: str, intent_id: str, subject: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = _json_request("POST", f"{self.base_url}/v1/intents", bearer_token=self.token, payload={"capability_id": capability_id, "intent_id": intent_id, "subject": subject, "payload": payload}, timeout=float(os.getenv("PLATFORM_BROKER_TIMEOUT_SECONDS", "30")))
        status = int(response.get("status_code", 0))
        if status and status not in {200, 201, 202}:
            raise RuntimeError(f"platform broker refused intent: {response}")
        return response


class JsonlAuditSink:
    def __init__(self, path: Optional[str] = None):
        self.path = Path(path or require_env("AI_AUDIT_LOG"))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: Any) -> None:
        if is_dataclass(record):
            record = asdict(record)
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
            handle.flush()
            os.fsync(handle.fileno())

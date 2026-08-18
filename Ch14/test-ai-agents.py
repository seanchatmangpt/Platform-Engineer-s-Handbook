#!/usr/bin/env python3
"""Source-level refusal tests for the Chapter 14 production execution surfaces."""
from __future__ import annotations

import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRODUCTION_FILES = [
    ROOT / "runtime_clients.py",
    ROOT / "incident-agent.py",
    ROOT / "alert-correlator.py",
    ROOT / "runbook-automator.py",
    ROOT / "measure-ai-impact.py",
    ROOT / "agents/multi_agent_system.py",
    ROOT / "platform_chatbot/rag_pipeline.py",
    ROOT / "platform_chatbot/incident_triage.py",
]
FORBIDDEN = (
    "MockLLM",
    "MockEmbeddings",
    "MockVectorStore",
    "MemoryActuator",
    "mock_mode",
    "generate_demo_incidents",
    "create_sample_alerts",
    "Simulate action execution",
)


class ProductionAISourceTests(unittest.TestCase):
    def test_execution_surfaces_compile(self):
        for path in PRODUCTION_FILES:
            self.assertTrue(path.is_file(), path)
            compile(path.read_text(encoding="utf-8"), str(path), "exec")

    def test_execution_surfaces_have_no_fake_fallbacks(self):
        for path in PRODUCTION_FILES:
            text = path.read_text(encoding="utf-8")
            for token in FORBIDDEN:
                self.assertNotIn(token, text, f"{token} present in {path.relative_to(ROOT)}")

    def test_real_observation_clients_are_present(self):
        text = (ROOT / "runtime_clients.py").read_text(encoding="utf-8")
        for marker in ("class KubernetesRuntime", "class PrometheusClient", "class AlertmanagerClient", "class AnthropicRuntime", "class BRCEIntentClient"):
            self.assertIn(marker, text)

    def test_state_changes_use_brce_intent_client(self):
        for relative in ("incident-agent.py", "runbook-automator.py", "agents/multi_agent_system.py"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("BRCEIntentClient", text, relative)

    def test_runbook_diagnostics_do_not_use_shell(self):
        text = (ROOT / "runbook-automator.py").read_text(encoding="utf-8")
        self.assertIn("subprocess.run", text)
        self.assertNotIn("shell=True", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

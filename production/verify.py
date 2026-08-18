#!/usr/bin/env python3
"""Static production-architecture closure verifier.

No network, cluster, or cloud access is required. This verifies repository closure only;
it does not claim runtime ALIVE status for any external system.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "production"

REQUIRED = [
    PROD / "README.md",
    PROD / "architecture/enterprise.yaml",
    PROD / "architecture/chapter-capability-map.yaml",
    PROD / "contracts/platform.yaml",
    PROD / "governance/controls.yaml",
    PROD / "ontology/platform.ttl",
    PROD / "runtime/admission.py",
    PROD / "runtime/receipt.schema.json",
]

PUBLIC_ONTOLOGY_MARKERS = ["prov:", "dcat:", "dcterms:", "skos:", "sh:", "odrl:", "foaf:", "qudt:", "sosa:"]
CHANNEL_MARKERS = ["portal:", "cli:", "api:", "mcp:", "a2a:", "gitops:"]


def check() -> list[str]:
    errors: list[str] = []
    for path in REQUIRED:
        if not path.exists() or path.stat().st_size == 0:
            errors.append(f"missing-or-empty:{path.relative_to(ROOT)}")

    chapter_map = (PROD / "architecture/chapter-capability-map.yaml").read_text()
    for n in range(1, 15):
        marker = f"Ch{n:02d}:"
        if marker not in chapter_map:
            errors.append(f"chapter-not-mapped:{marker[:-1]}")

    ontology = (PROD / "ontology/platform.ttl").read_text()
    for marker in PUBLIC_ONTOLOGY_MARKERS:
        if marker not in ontology:
            errors.append(f"ontology-marker-missing:{marker}")

    contract = (PROD / "contracts/platform.yaml").read_text()
    for marker in CHANNEL_MARKERS:
        if marker not in contract:
            errors.append(f"interface-missing:{marker[:-1]}")
    if "ambient_execution_authority: false" not in contract:
        errors.append("ai-ambient-authority-not-disabled")

    controls = (PROD / "governance/controls.yaml").read_text()
    for family in ["identity:", "change:", "supply_chain:", "runtime:", "reliability:", "cost:", "data:", "ai:"]:
        if family not in controls:
            errors.append(f"control-family-missing:{family[:-1]}")

    schema = json.loads((PROD / "runtime/receipt.schema.json").read_text())
    for field in ["subject", "intent", "decision", "actuation", "evidence", "replay"]:
        if field not in schema.get("required", []):
            errors.append(f"receipt-required-field-missing:{field}")

    forbidden = ["TODO", "FIXME", "TBD"]
    for path in REQUIRED:
        if path.suffix in {".md", ".yaml", ".ttl", ".py", ".json"}:
            text = path.read_text()
            for token in forbidden:
                if token in text:
                    errors.append(f"placeholder:{path.relative_to(ROOT)}:{token}")
    return errors


def main() -> int:
    errors = check()
    report = {
        "status": "ALIVE" if not errors else "BUILD_BROKEN",
        "scope": "static-production-architecture-closure",
        "checked_chapters": 14,
        "errors": errors,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())

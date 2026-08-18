#!/usr/bin/env python3
"""Independent verifier and receipt projection for ggen-manufactured production consequences."""
from __future__ import annotations
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
LOCK = ROOT/'ggen/marketplace.lock.json'
REQUIRED = [
    ROOT/'runtime/generated_platform.py', ROOT/'runtime/dfcm_generated.py',
    ROOT/'runtime/persistent_ledger.py', ROOT/'runtime/platform_api.py',
    ROOT/'generated/platform-capabilities.json', ROOT/'generated/platform-adapters.json', ROOT/'generated/platform.openapi.yaml',
    ROOT/'docs/FORTUNE5_ARCHITECTURE_CATALOG.md', ROOT/'docs/FORTUNE5_CONTROL_MATRIX.md', ROOT/'docs/FORTUNE5_WORKFLOW_PATTERN_COVERAGE.md',
    ROOT/'generated/dfcm/DFCM_DEPLOYMENT.md', ROOT/'generated/dfcm/DEPLOYMENT.toml', ROOT/'generated/dfcm/BRCE_POLICY.json', ROOT/'generated/dfcm/RECEIPT_CONTRACT.json', ROOT/'generated/dfcm/REPLAY.md',
    ROOT/'generated/dfcm/verify.py', ROOT/'generated/dfcm/formal/DfcmAdmission.lean', ROOT/'generated/dfcm/formal/MFACT.json',
    ROOT/'generated/dfcm/enterprise/ENTERPRISE_READINESS.json', ROOT/'generated/dfcm/enterprise/CONTROL_CATALOG.json', ROOT/'generated/dfcm/enterprise/SLO_POLICY.json', ROOT/'generated/dfcm/enterprise/RESILIENCE.toml',
    ROOT/'generated/dfcm/enterprise/CHANGE_CONTROL.json', ROOT/'generated/dfcm/enterprise/DATA_BOUNDARIES.json', ROOT/'generated/dfcm/enterprise/CAPACITY_ENVELOPE.toml', ROOT/'generated/dfcm/enterprise/SUPPLY_CHAIN.json', ROOT/'generated/dfcm/enterprise/AUDIT_POLICY.json', ROOT/'generated/dfcm/enterprise/CHAOS_POLICY.json', ROOT/'generated/dfcm/enterprise/ENTERPRISE_INVARIANTS.json', ROOT/'generated/dfcm/enterprise/enterprise_verify.py',
    ROOT/'src/gdmcp/python/protocol.py', ROOT/'src/gdmcp/rust/protocol.rs', ROOT/'src/gdmcp/typescript/protocol.ts',
]
FORBIDDEN_PLATFORM_RUNTIME = ('MemoryActuator', 'mock_mode', 'MockLLM', 'MockVectorStore')
SHA40 = re.compile(r'^[0-9a-f]{40}$')


def identities():
    lock = json.loads(LOCK.read_text()) if LOCK.is_file() else {}
    return {
        'subject_sha': os.environ.get('PRODUCTION_SUBJECT_SHA', 'UNKNOWN'),
        'base_sha': os.environ.get('PRODUCTION_BASE_SHA', 'UNKNOWN'),
        'marketplace_sha': lock.get('marketplace', {}).get('commit', 'UNKNOWN'),
        'ggen_sha': lock.get('ggen', {}).get('commit', 'UNKNOWN'),
        'pack_trees': {name: item.get('tree', 'UNKNOWN') for name, item in sorted(lock.get('packs', {}).items())},
    }


def deployment_paths(provider):
    root = ROOT/'generated/deployment'/provider/'.ggen'
    return [
        root/'packs.lock',
        root/'bblocks/plans'/provider/'fortune5-complete.json',
        root/'bblocks/receipts'/provider/'fortune5-complete-plan-intent.json',
        root/'bblocks/receipts'/provider/'fortune5-complete-plan-result.json',
        root/'bblocks/receipts'/provider/'fortune5-complete-enable-intent.json',
        root/'bblocks/receipts'/provider/'fortune5-complete-enable-result.json',
    ]


def _check_provider_receipts(provider, errors):
    paths = deployment_paths(provider)
    plan = paths[1]
    if plan.is_file():
        text = plan.read_text(encoding='utf-8')
        for token in ('fortune5-complete', provider):
            if token not in text:
                errors.append(f'bblock-plan-marker-missing:{provider}:{token}')
    for receipt_path in paths[2:]:
        if not receipt_path.is_file():
            continue
        try:
            payload = json.loads(receipt_path.read_text(encoding='utf-8'))
        except Exception as exc:
            errors.append(f'bblock-receipt-json-invalid:{provider}:{receipt_path.name}:{exc}')
            continue
        serialized = json.dumps(payload, sort_keys=True)
        if provider not in serialized:
            errors.append(f'bblock-receipt-provider-missing:{provider}:{receipt_path.name}')
        if 'fortune5-complete' not in serialized:
            errors.append(f'bblock-receipt-group-missing:{provider}:{receipt_path.name}')


def check():
    errors = []
    for path in REQUIRED + deployment_paths('aws') + deployment_paths('gcp'):
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f'missing-or-empty:{path.relative_to(ROOT)}')
    ids = identities()
    if os.environ.get('CI', '').lower() == 'true':
        for field in ('subject_sha', 'base_sha', 'marketplace_sha', 'ggen_sha'):
            if not SHA40.fullmatch(ids[field]):
                errors.append(f'identity-not-exact:{field}:{ids[field]}')
        if any(not SHA40.fullmatch(value) for value in ids['pack_trees'].values()):
            errors.append('pack-tree-identity-not-exact')
    caps = ROOT/'generated/platform-capabilities.json'
    if caps.is_file():
        try:
            payload = json.loads(caps.read_text())
        except Exception as exc:
            errors.append(f'capabilities-json-invalid:{exc}')
        else:
            if len(payload.get('capabilities', [])) != 14:
                errors.append('capability-count-not-14')
            if payload.get('ambient_execution_authority') is not False:
                errors.append('ambient-authority-enabled')
            if len(payload.get('channels', [])) < 7:
                errors.append('interface-channel-count-below-7')
    adapters = ROOT/'generated/platform-adapters.json'
    if adapters.is_file():
        try:
            payload = json.loads(adapters.read_text())
        except Exception as exc:
            errors.append(f'adapter-json-invalid:{exc}')
        else:
            rows = payload.get('adapters', [])
            if len(rows) != 14:
                errors.append('adapter-count-not-14')
            if payload.get('actuation') != 'BRCE_ONLY' or payload.get('ambient_execution_authority') is not False:
                errors.append('adapter-actuation-boundary-invalid')
            if payload.get('providers') != ['aws', 'gcp']:
                errors.append('adapter-provider-closure-invalid')
            for row in rows:
                path = REPO/row.get('implementation_path', '')
                if not path.is_file():
                    errors.append(f'chapter-implementation-missing:{row.get("chapter")}:{row.get("implementation_path")}')
                if not row.get('deployment_group'):
                    errors.append(f'deployment-group-missing:{row.get("capability_id")}')
    runtime = ROOT/'runtime/generated_platform.py'
    if runtime.is_file():
        text = runtime.read_text()
        for token in ('dfcm.BRCE', 'AdmissionBoundary', 'dfcm.construct', 'source_identity', 'base_identity', 'environment_identity', 'authority', 'REFUSED:MISSING_RECEIPT_LEDGER', 'class ProductionActuator', 'rollout_restart', 'patch_container_resources', 'github_upsert_file'):
            if token not in text:
                errors.append(f'platform-broker-marker-missing:{token}')
        for token in FORBIDDEN_PLATFORM_RUNTIME:
            if token in text:
                errors.append(f'fake-platform-runtime:{token}')
    ledger = ROOT/'runtime/persistent_ledger.py'
    if ledger.is_file():
        text = ledger.read_text()
        for token in ('class SqliteReceiptLedger', 'journal_mode=WAL', 'synchronous=FULL', 'ReceiptLedger.verify', 'BEGIN IMMEDIATE'):
            if token not in text:
                errors.append(f'persistent-ledger-marker-missing:{token}')
    api = ROOT/'runtime/platform_api.py'
    if api.is_file():
        text = api.read_text()
        for token in ('ThreadingHTTPServer', '/v1/intents', '/healthz', 'PLATFORM_API_TOKEN', 'SqliteReceiptLedger', 'ProductionActuator'):
            if token not in text:
                errors.append(f'platform-api-marker-missing:{token}')
    dfcm = ROOT/'runtime/dfcm_generated.py'
    if dfcm.is_file():
        text = dfcm.read_text()
        for token in ('class BRCE', 'class ReceiptLedger', 'class HookBoundary', 'PARTIAL_ALIVE', 'REFUSED', 'receipted', 'source_identity', 'base_identity', 'toolchain_identity', 'environment_identity', 'from blake3 import blake3'):
            if token not in text:
                errors.append(f'dfcm-marker-missing:{token}')
        if 'blake2b' in text:
            errors.append('dfcm-noncanonical-digest:blake2b')
    for provider in ('aws', 'gcp'):
        _check_provider_receipts(provider, errors)
    return errors


def _is_invocation_receipt(path: Path) -> bool:
    parts = path.relative_to(ROOT).parts
    return 'deployment' in parts and 'bblocks' in parts and 'receipts' in parts


def consequence_files():
    """Return deterministic generated code/topology only; invocation receipts remain separately required and verified."""
    files = []
    for root in [ROOT/'generated', ROOT/'docs', ROOT/'src/gdmcp']:
        if root.exists():
            files.extend(path for path in root.rglob('*') if path.is_file() and path.name != 'manufacture-receipt.json' and not _is_invocation_receipt(path))
    for path in [ROOT/'runtime/generated_platform.py', ROOT/'runtime/dfcm_generated.py', ROOT/'runtime/persistent_ledger.py', ROOT/'runtime/platform_api.py', ROOT/'ggen.lock']:
        if path.is_file():
            files.append(path)
    return sorted(set(files), key=lambda path: str(path.relative_to(ROOT)))


def digest():
    h = hashlib.sha256()
    for path in consequence_files():
        rel = str(path.relative_to(ROOT)).encode()
        data = path.read_bytes()
        h.update(len(rel).to_bytes(4, 'big'))
        h.update(rel)
        h.update(len(data).to_bytes(8, 'big'))
        h.update(data)
    return h.hexdigest()


def receipt(errors):
    return {
        'schema': 'https://ggen.dev/platform-engineering/manufacture-receipt/v1',
        'status': 'ALIVE' if not errors else 'BUILD_BROKEN',
        'scope': 'full-production-generated-consequences',
        'identities': identities(),
        'required_files': len(REQUIRED) + 12,
        'deterministic_consequence_files': len(consequence_files()),
        'deterministic_consequence_digest_sha256': digest(),
        'providers': ['aws', 'gcp'],
        'deployment_bundle': 'fortune5-complete',
        'replay': 'second manufacture must reproduce deterministic code/topology digest; provider invocation receipts are separately required and verified',
        'errors': errors,
    }


def main():
    if '--digest' in sys.argv:
        print(digest())
        return 0
    errors = check()
    print(json.dumps(receipt(errors), indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == '__main__':
    raise SystemExit(main())

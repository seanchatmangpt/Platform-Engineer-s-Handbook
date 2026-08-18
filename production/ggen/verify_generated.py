#!/usr/bin/env python3
"""Independent verifier and receipt projection for ggen-manufactured production consequences."""
from __future__ import annotations
import hashlib, json, os, re, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
LOCK=ROOT/'ggen/marketplace.lock.json'
REQUIRED=[
 ROOT/'runtime/generated_platform.py', ROOT/'runtime/dfcm_generated.py',
 ROOT/'generated/platform-capabilities.json', ROOT/'generated/platform.openapi.yaml',
 ROOT/'docs/FORTUNE5_ARCHITECTURE_CATALOG.md', ROOT/'docs/FORTUNE5_CONTROL_MATRIX.md', ROOT/'docs/FORTUNE5_WORKFLOW_PATTERN_COVERAGE.md',
 ROOT/'generated/dfcm/DFCM_DEPLOYMENT.md', ROOT/'generated/dfcm/DEPLOYMENT.toml',
 ROOT/'generated/dfcm/BRCE_POLICY.json', ROOT/'generated/dfcm/RECEIPT_CONTRACT.json', ROOT/'generated/dfcm/REPLAY.md',
 ROOT/'generated/dfcm/verify.py', ROOT/'generated/dfcm/formal/DfcmAdmission.lean', ROOT/'generated/dfcm/formal/MFACT.json',
 ROOT/'generated/dfcm/enterprise/ENTERPRISE_READINESS.json', ROOT/'generated/dfcm/enterprise/CONTROL_CATALOG.json',
 ROOT/'generated/dfcm/enterprise/SLO_POLICY.json', ROOT/'generated/dfcm/enterprise/RESILIENCE.toml',
 ROOT/'generated/dfcm/enterprise/CHANGE_CONTROL.json', ROOT/'generated/dfcm/enterprise/DATA_BOUNDARIES.json',
 ROOT/'generated/dfcm/enterprise/CAPACITY_ENVELOPE.toml', ROOT/'generated/dfcm/enterprise/SUPPLY_CHAIN.json',
 ROOT/'generated/dfcm/enterprise/AUDIT_POLICY.json', ROOT/'generated/dfcm/enterprise/CHAOS_POLICY.json',
 ROOT/'generated/dfcm/enterprise/ENTERPRISE_INVARIANTS.json', ROOT/'generated/dfcm/enterprise/enterprise_verify.py',
 ROOT/'src/gdmcp/python/protocol.py', ROOT/'src/gdmcp/rust/protocol.rs', ROOT/'src/gdmcp/typescript/protocol.ts'
]
FORBIDDEN_RUNTIME=('subprocess','os.system','kubectl','boto3','requests.')
SHA40=re.compile(r'^[0-9a-f]{40}$')

def identities():
    lock=json.loads(LOCK.read_text()) if LOCK.is_file() else {}
    return {
        'subject_sha': os.environ.get('PRODUCTION_SUBJECT_SHA','UNKNOWN'),
        'base_sha': os.environ.get('PRODUCTION_BASE_SHA','UNKNOWN'),
        'marketplace_sha': lock.get('marketplace',{}).get('commit','UNKNOWN'),
        'ggen_sha': lock.get('ggen',{}).get('commit','UNKNOWN'),
        'pack_trees': {name:item.get('tree','UNKNOWN') for name,item in sorted(lock.get('packs',{}).items())},
    }

def check():
    errors=[]
    for p in REQUIRED:
        if not p.is_file() or p.stat().st_size == 0:
            errors.append(f'missing-or-empty:{p.relative_to(ROOT)}')
    ids=identities()
    if os.environ.get('CI','').lower() == 'true':
        for field in ('subject_sha','base_sha','marketplace_sha','ggen_sha'):
            if not SHA40.fullmatch(ids[field]): errors.append(f'identity-not-exact:{field}:{ids[field]}')
        if any(not SHA40.fullmatch(value) for value in ids['pack_trees'].values()): errors.append('pack-tree-identity-not-exact')
    caps=ROOT/'generated/platform-capabilities.json'
    if caps.is_file():
        try:
            payload=json.loads(caps.read_text())
        except Exception as exc:
            errors.append(f'capabilities-json-invalid:{exc}')
        else:
            if len(payload.get('capabilities',[])) != 14: errors.append('capability-count-not-14')
            if payload.get('ambient_execution_authority') is not False: errors.append('ambient-authority-enabled')
            if len(payload.get('channels',[])) < 7: errors.append('interface-channel-count-below-7')
    rt=ROOT/'runtime/generated_platform.py'
    if rt.is_file():
        text=rt.read_text()
        for token in ['dfcm.BRCE','AdmissionBoundary','dfcm.construct','source_identity','base_identity','environment_identity','authority']:
            if token not in text: errors.append(f'platform-broker-marker-missing:{token}')
        for token in FORBIDDEN_RUNTIME:
            if token in text: errors.append(f'ambient-actuator-token:{token}')
    dfcm=ROOT/'runtime/dfcm_generated.py'
    if dfcm.is_file():
        text=dfcm.read_text()
        for token in ['class BRCE','class ReceiptLedger','class HookBoundary','PARTIAL_ALIVE','REFUSED','receipted','source_identity','base_identity','toolchain_identity','environment_identity','from blake3 import blake3']:
            if token not in text: errors.append(f'dfcm-marker-missing:{token}')
        if 'blake2b' in text: errors.append('dfcm-noncanonical-digest:blake2b')
    for path in [ROOT/'generated/dfcm/enterprise/ENTERPRISE_READINESS.json', ROOT/'generated/dfcm/enterprise/CONTROL_CATALOG.json', ROOT/'generated/dfcm/enterprise/ENTERPRISE_INVARIANTS.json']:
        if path.is_file():
            try: json.loads(path.read_text())
            except Exception as exc: errors.append(f'generated-json-invalid:{path.relative_to(ROOT)}:{exc}')
    return errors

def digest():
    h=hashlib.sha256()
    for p in sorted(REQUIRED, key=lambda p:str(p)):
        if p.is_file():
            rel=str(p.relative_to(ROOT)).encode(); data=p.read_bytes()
            h.update(len(rel).to_bytes(4,'big')); h.update(rel); h.update(len(data).to_bytes(8,'big')); h.update(data)
    return h.hexdigest()

def receipt(errors):
    return {
        'schema':'https://ggen.dev/platform-engineering/manufacture-receipt/v1',
        'status':'ALIVE' if not errors else 'BUILD_BROKEN',
        'scope':'generated-consumer-consequences',
        'identities':identities(),
        'required_files':len(REQUIRED),
        'consequence_digest_sha256':digest(),
        'replay':'second ggen manufacture must produce the same consequence digest',
        'errors':errors,
    }

def main():
    if '--digest' in sys.argv:
        print(digest()); return 0
    errors=check()
    print(json.dumps(receipt(errors),indent=2,sort_keys=True))
    return 0 if not errors else 1
if __name__=='__main__': raise SystemExit(main())

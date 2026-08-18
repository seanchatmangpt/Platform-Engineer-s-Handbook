#!/usr/bin/env python3
"""Production platform closure verifier: authored source by default, generated consequences on demand."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; PROD=ROOT/'production'
SOURCE_REQUIRED=[
 PROD/'README.md',PROD/'architecture/enterprise.yaml',PROD/'architecture/chapter-capability-map.yaml',
 PROD/'contracts/platform.yaml',PROD/'governance/controls.yaml',PROD/'ontology/platform.ttl',
 PROD/'runtime/admission.py',PROD/'runtime/receipt.schema.json',PROD/'ggen.toml',
 PROD/'ggen/domain.base.ttl',PROD/'ggen/build_domain.py',PROD/'ggen/marketplace.lock.json',
 PROD/'ggen/manufacture.sh',PROD/'ggen/verify_generated.py',
 PROD/'ggen/templates/platform_runtime.py.tmpl',PROD/'ggen/templates/platform_capabilities.json.tmpl',
 PROD/'ggen/templates/platform_openapi.yaml.tmpl'
]
PUBLIC_ONTOLOGY_MARKERS=['prov:','dcat:','dcterms:','skos:','sh:','odrl:','foaf:','qudt:','sosa:']
CHANNEL_MARKERS=['portal:','cli:','api:','mcp:','a2a:','gitops:']
EXPECTED_MARKETPLACE='1de960e783ee62e5db34392bc38db4541e464a54'
EXPECTED_GGEN='402cecdff8784767eb9f26e235d87c759610c066'
EXPECTED_PACKS={
 'dfcm-pack':'1013f463a6ade98ed3e93d6d64e5826a42776df1',
 'fortune5-architecture-pack':'bf7f9725ed4062c3d5fc0dd13ba6acab34177811',
 'gdmcp-pack':'9b3e867b8a29beaa7ed9053e12cdc056a78f229c',
}

def check_source():
    errors=[]
    for p in SOURCE_REQUIRED:
        if not p.exists() or p.stat().st_size==0: errors.append(f'missing-or-empty:{p.relative_to(ROOT)}')
    chapter_path=PROD/'architecture/chapter-capability-map.yaml'
    chapter_map=chapter_path.read_text() if chapter_path.is_file() else ''
    for n in range(1,15):
        if f'Ch{n:02d}:' not in chapter_map: errors.append(f'chapter-not-mapped:Ch{n:02d}')
    ontology_path=PROD/'ontology/platform.ttl'; ontology=ontology_path.read_text() if ontology_path.is_file() else ''
    for marker in PUBLIC_ONTOLOGY_MARKERS:
        if marker not in ontology: errors.append(f'ontology-marker-missing:{marker}')
    contract_path=PROD/'contracts/platform.yaml'; contract=contract_path.read_text() if contract_path.is_file() else ''
    for marker in CHANNEL_MARKERS:
        if marker not in contract: errors.append(f'interface-missing:{marker[:-1]}')
    if 'ambient_execution_authority: false' not in contract: errors.append('ai-ambient-authority-not-disabled')
    controls_path=PROD/'governance/controls.yaml'; controls=controls_path.read_text() if controls_path.is_file() else ''
    for family in ['identity:','change:','supply_chain:','runtime:','reliability:','cost:','data:','ai:']:
        if family not in controls: errors.append(f'control-family-missing:{family[:-1]}')
    schema_path=PROD/'runtime/receipt.schema.json'; schema=json.loads(schema_path.read_text()) if schema_path.is_file() else {}
    for field in ['subject','intent','decision','actuation','evidence','replay']:
        if field not in schema.get('required',[]): errors.append(f'receipt-required-field-missing:{field}')
    domain_path=PROD/'ggen/domain.base.ttl'; domain=domain_path.read_text() if domain_path.is_file() else ''
    for n in range(1,15):
        if f'peh:chapter "Ch{n:02d}"' not in domain: errors.append(f'ggen-domain-chapter-missing:Ch{n:02d}')
    builder_path=PROD/'ggen/build_domain.py'; builder=builder_path.read_text() if builder_path.is_file() else ''
    if 'range(1,44)' not in builder or 'f5:WorkflowPatternEvidence' not in builder: errors.append('wcp-evidence-builder-incomplete')
    for marker in ['f5:broker "BRCE"','f5:directActuation false','f5:receiptRequired true','f5:receiptAlgorithm "blake3"','peh:cold-path']:
        if marker not in domain: errors.append(f'ggen-domain-marker-missing:{marker}')
    manifest_path=PROD/'ggen.toml'; manifest=manifest_path.read_text() if manifest_path.is_file() else ''
    for pack in ['fortune5-architecture-pack','gdmcp-pack']:
        if pack not in manifest: errors.append(f'ggen-pack-missing:{pack}')
    lock_path=PROD/'ggen/marketplace.lock.json'; lock=json.loads(lock_path.read_text()) if lock_path.is_file() else {}
    if lock.get('marketplace',{}).get('commit') != EXPECTED_MARKETPLACE: errors.append('marketplace-pin-drift')
    if lock.get('ggen',{}).get('commit') != EXPECTED_GGEN: errors.append('ggen-pin-drift')
    packs=lock.get('packs',{})
    if 'dfcm-full-deployment-pack' in packs: errors.append('refused-defective-pack:dfcm-full-deployment-pack')
    for name,tree in EXPECTED_PACKS.items():
        if packs.get(name,{}).get('tree') != tree: errors.append(f'pack-tree-pin-drift:{name}')
    workflow=(ROOT/'.github/workflows/production-architecture.yml').read_text()
    if 'blake3==1.0.9' not in workflow: errors.append('blake3-runtime-pin-drift')
    for path in SOURCE_REQUIRED:
        if path.is_file() and path.suffix in {'.md','.yaml','.ttl','.py','.json','.toml','.txt','.tmpl','.sh'}:
            text=path.read_text()
            for token in ['TODO','FIXME','TBD']:
                if token in text: errors.append(f'placeholder:{path.relative_to(ROOT)}:{token}')
    return errors

def check_generated():
    import importlib.util
    path=PROD/'ggen/verify_generated.py'; spec=importlib.util.spec_from_file_location('verify_generated',path)
    mod=importlib.util.module_from_spec(spec); assert spec.loader; spec.loader.exec_module(mod); return mod.check()

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--require-generated',action='store_true'); args=parser.parse_args()
    errors=check_source(); scope='source-production-manufacture-closure'
    if args.require_generated:
        errors.extend(check_generated()); scope='source-and-generated-production-closure'
    report={'status':'ALIVE' if not errors else 'BUILD_BROKEN','scope':scope,'checked_chapters':14,'errors':errors}
    print(json.dumps(report,indent=2,sort_keys=True)); return 0 if not errors else 1
if __name__=='__main__': sys.exit(main())

#!/usr/bin/env python3
from pathlib import Path
HERE=Path(__file__).resolve().parent
base=(HERE/'domain.base.ttl').read_text().rstrip()+"\n"
lines=[base, 'peh:program f5:hasWorkflowPatternEvidence '+', '.join(f'peh:wcp{i:02d}-evidence' for i in range(1,44))+' .']
for i in range(1,44):
    lines.append(f'peh:wcp{i:02d}-evidence a f5:WorkflowPatternEvidence ; f5:workflowPattern f5:WCP{i:02d} ; f5:implementationEvidence "wasm4pm:wcp{i:02d}" ; f5:positiveWitness "fixtures/wcp{i:02d}/positive" ; f5:negativeFalsifier "fixtures/wcp{i:02d}/negative" ; f5:receiptVerifier "receipts/wcp{i:02d}.json" .')
(HERE/'domain.ttl').write_text("\n".join(lines)+"\n")

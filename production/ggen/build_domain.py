#!/usr/bin/env python3
from pathlib import Path
HERE=Path(__file__).resolve().parent
base=(HERE/'domain.base.ttl').read_text().rstrip()+"\n"
implementations={
'platform-product-governance':('Ch01/platform-config.yaml','policy-governance'),
'runtime-gitops':('Ch02/platform-services.yaml','container-runtime'),
'identity-security':('Ch03/rbac-platform-admin.yaml','workload-identity'),
'observability':('Ch04/otel-collector-deployment.yaml','observability'),
'developer-experience':('Ch05/platform-deploy.sh','testing'),
'developer-portal':('Ch06/backstage-helm-values.yaml','container-runtime'),
'onboarding':('Ch07/onboarding-api.py','workload-identity'),
'software-delivery':('Ch08/reusable-workflows/deploy.yaml','artifact-registry'),
'infrastructure-service':('Ch09/crossplane-providers.yaml','fortune5-platform'),
'starter-kits':('Ch10/templates/backend-service/v1/template.yaml','artifact-registry'),
'policy-compliance':('Ch11/constraint-template-security-baselines.yaml','policy-governance'),
'finops-scaling':('Ch12/opencost-cost-allocation.yaml','observability'),
'resilience':('Ch13/velero-schedule.yaml','resilience-dr'),
'ai-augmentation':('Ch14/ai-guardrails.py','fortune5-control-plane'),
}
lines=[base,
'peh:implementationPath a rdf:Property .',
'peh:deploymentGroup a rdf:Property .',
'peh:program f5:hasWorkflowPatternEvidence '+', '.join(f'peh:wcp{i:02d}-evidence' for i in range(1,44))+' .']
for capability,(path,group) in implementations.items():
    lines.append(f'peh:{capability} peh:implementationPath "{path}" ; peh:deploymentGroup "{group}" .')
for i in range(1,44):
    lines.append(f'peh:wcp{i:02d}-evidence a f5:WorkflowPatternEvidence ; f5:workflowPattern f5:WCP{i:02d} ; f5:implementationEvidence "wasm4pm:wcp{i:02d}" ; f5:positiveWitness "fixtures/wcp{i:02d}/positive" ; f5:negativeFalsifier "fixtures/wcp{i:02d}/negative" ; f5:receiptVerifier "receipts/wcp{i:02d}.json" .')
(HERE/'domain.ttl').write_text("\n".join(lines)+"\n")

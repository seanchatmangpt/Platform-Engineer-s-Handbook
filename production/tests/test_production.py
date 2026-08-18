from pathlib import Path
import importlib.util, sys, unittest
ROOT=Path(__file__).resolve().parents[2]
GENERATED_PLATFORM=ROOT/'production/runtime/generated_platform.py'
GENERATED_DFCM=ROOT/'production/runtime/dfcm_generated.py'

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod

verify=load('verify',ROOT/'production/verify.py')
admission=load('admission',ROOT/'production/runtime/admission.py')

class ProductionClosureTests(unittest.TestCase):
    def test_static_closure(self):
        self.assertEqual([],verify.check_source())

    @unittest.skipUnless(GENERATED_PLATFORM.is_file() and GENERATED_DFCM.is_file(), 'generated consequences unavailable in source-only checkout')
    def test_generated_closure(self):
        self.assertEqual([],verify.check_generated())

    def test_safe_intent_is_admitted(self):
        intent=admission.Intent(id='i-1',actor='test',operation='deploy',subject_kind='service',subject_id='orders',subject_digest='sha256:abc',idempotency_key='k-1')
        decision=admission.admit(intent,['CHG-001','SSC-001'])
        self.assertEqual('ADMITTED',decision.status)
        receipt=admission.pre_actuation_receipt(intent,decision)
        self.assertEqual('NOT_RUN',receipt['actuation']['status'])
        self.assertEqual('external-broker-required',receipt['actuation']['executor'])

    def test_destructive_intent_without_recovery_is_refused(self):
        intent=admission.Intent(id='i-2',actor='test',operation='destroy',subject_kind='database',subject_id='prod-db',subject_digest='sha256:def',idempotency_key='k-2',destructive=True)
        decision=admission.admit(intent,['CHG-003'])
        self.assertEqual('REFUSED',decision.status)
        self.assertIn('destructive-change-without-recovery-proof',decision.reasons)

    @unittest.skipUnless(GENERATED_PLATFORM.is_file() and GENERATED_DFCM.is_file(), 'generated consequences unavailable in source-only checkout')
    def test_generated_brce_execution_and_replay(self):
        # Import through the production package path so generated_platform and this
        # assertion share the same Standing/Evidence class identities.
        from production.runtime import dfcm_generated as dfcm
        from production.runtime import generated_platform as platform
        self.assertEqual(14,len(platform.CAPABILITIES))
        broker=platform.PlatformBroker(
            platform.MemoryActuator(),
            source_identity='test-source@sha256:1111111111111111111111111111111111111111111111111111111111111111',
            base_identity='test-base@sha256:2222222222222222222222222222222222222222222222222222222222222222',
            environment_identity='memory-test',
            authority='test-authority',
        )
        receipt,evidence=broker.execute('software-delivery','i-generated','service/orders',b'release-v1')
        self.assertTrue(evidence.executed)
        self.assertTrue(evidence.verified)
        self.assertTrue(evidence.receipted)
        self.assertTrue(broker.ledger.replay())
        self.assertEqual(dfcm.Standing.ALIVE,dfcm.standing(evidence,True))
        self.assertEqual('promote-release',receipt.operation)
        self.assertEqual('test-authority',receipt.authority)
        self.assertTrue(receipt.replay_identity)

if __name__=='__main__': unittest.main()

from pathlib import Path
import importlib.util
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]

spec = importlib.util.spec_from_file_location("verify", ROOT / "production/verify.py")
verify = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = verify
assert spec.loader
spec.loader.exec_module(verify)

spec2 = importlib.util.spec_from_file_location("admission", ROOT / "production/runtime/admission.py")
admission = importlib.util.module_from_spec(spec2)
sys.modules[spec2.name] = admission
assert spec2.loader
spec2.loader.exec_module(admission)


class ProductionClosureTests(unittest.TestCase):
    def test_static_closure(self):
        self.assertEqual([], verify.check())

    def test_safe_intent_is_admitted(self):
        intent = admission.Intent(
            id="i-1",
            actor="test",
            operation="deploy",
            subject_kind="service",
            subject_id="orders",
            subject_digest="sha256:abc",
            idempotency_key="k-1",
        )
        decision = admission.admit(intent, ["CHG-001", "SSC-001"])
        self.assertEqual("ADMITTED", decision.status)
        receipt = admission.pre_actuation_receipt(intent, decision)
        self.assertEqual("NOT_RUN", receipt["actuation"]["status"])
        self.assertEqual("external-broker-required", receipt["actuation"]["executor"])

    def test_destructive_intent_without_recovery_is_refused(self):
        intent = admission.Intent(
            id="i-2",
            actor="test",
            operation="destroy",
            subject_kind="database",
            subject_id="prod-db",
            subject_digest="sha256:def",
            idempotency_key="k-2",
            destructive=True,
        )
        decision = admission.admit(intent, ["CHG-003"])
        self.assertEqual("REFUSED", decision.status)
        self.assertIn("destructive-change-without-recovery-proof", decision.reasons)


if __name__ == "__main__":
    unittest.main()

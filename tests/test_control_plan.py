import unittest

from ..services.control_plan import ControlChannel, ControlPlan, ControlPlanError


class ControlPlanTests(unittest.TestCase):
    def test_modes_are_stable_and_independent_from_pipeline(self) -> None:
        plan = ControlPlan.from_modes(
            ("reference", "pose"),
            fidelity="strict",
            content_mode="free",
            pipeline="base",
        )

        self.assertEqual(plan.modes, ("pose", "reference"))
        self.assertEqual(plan.fidelity, "strict")
        self.assertEqual(plan.content_mode, "free")
        self.assertEqual(plan.pipeline, "base")

    def test_duplicate_channels_are_rejected(self) -> None:
        with self.assertRaises(ControlPlanError):
            ControlPlan((ControlChannel("pose"), ControlChannel("pose")))

    def test_reference_scope_cannot_be_applied_to_pose(self) -> None:
        with self.assertRaises(ControlPlanError):
            ControlChannel("pose", reference_scope="style")

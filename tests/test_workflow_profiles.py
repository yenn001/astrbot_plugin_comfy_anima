"""Workflow prompt/negative node id pairing and override tests."""

import json
import unittest
from pathlib import Path

from ..core.workflow_profiles import (
    WorkflowProfileError,
    _workflow_node_overrides,
    load_workflow_profile,
)
from ..models import PluginSettings

BASE = Path(__file__).resolve().parents[1] / "workflow"


class WorkflowNodeIdAuditTests(unittest.TestCase):
    def test_all_generation_workflow_manifests_pair_with_nodes(self) -> None:
        checked = 0
        for manifest in sorted((BASE / "manifests").glob("*.json")):
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            workflow_file = payload.get("workflow_file")
            workflow_path = BASE / workflow_file
            if not workflow_path.is_file():
                self.fail(f"missing workflow file {workflow_file}")
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            bindings = payload.get("bindings") or {}
            positive = bindings.get("positive_prompt")
            negative = bindings.get("negative_prompt")
            if positive is None and negative is None:
                continue
            for label, binding in (("positive", positive), ("negative", negative)):
                if binding is None:
                    continue
                checked += 1
                node = workflow.get(str(binding.get("node_id") or ""))
                self.assertIsNotNone(
                    node,
                    f"{manifest.stem} {label} node missing",
                )
                input_name = binding.get("input")
                self.assertIn(
                    input_name,
                    node.get("inputs") or {},
                    f"{manifest.stem} {label} input missing",
                )
                self.assertEqual(
                    node.get("class_type"),
                    "CLIPTextEncode",
                    f"{manifest.stem} {label} unexpected class",
                )
        self.assertGreaterEqual(checked, 20)

    def test_overrides_parse_and_apply(self) -> None:
        self.assertEqual(
            _workflow_node_overrides(["anima_base_api=99"]),
            {"anima_base_api": "99"},
        )
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "custom_legacy_api.json"
            path.write_text(
                json.dumps(
                    {
                        "99": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
                        "98": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
                    }
                ),
                encoding="utf-8",
            )
            settings = PluginSettings.from_mapping(
                {
                    "workflow_positive_node_overrides": [
                        "custom_legacy_api=99"
                    ],
                    "workflow_negative_node_overrides": [
                        "custom_legacy_api=98"
                    ],
                }
            )
            profile = load_workflow_profile(path, settings)
        self.assertEqual(profile.prompt.node_id, "99")
        self.assertEqual(profile.negative.node_id, "98")

    def test_invalid_override_format_is_rejected(self) -> None:
        with self.assertRaises(WorkflowProfileError):
            _workflow_node_overrides(["no_separator"])

    def test_missing_override_node_is_rejected(self) -> None:
        settings = PluginSettings.from_mapping(
            {"workflow_positive_node_overrides": ["anima_base_api=99999"]}
        )
        with self.assertRaises(WorkflowProfileError):
            load_workflow_profile(BASE / "anima_base_api.json", settings)


if __name__ == "__main__":
    unittest.main()

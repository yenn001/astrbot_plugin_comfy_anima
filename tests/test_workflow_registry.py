"""Tests for safe workflow discovery and hot selection."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ..core.workflow_registry import WorkflowRegistry, WorkflowRegistryError
from ..models import GenerationOptions, PluginSettings


def _write_workflow(path: Path, prompt_node_id: str = "210") -> None:
    """Write a minimal API workflow accepted by ``WorkflowBuilder``."""
    workflow = {
        prompt_node_id: {"inputs": {"positive": ""}},
        "13": {"inputs": {"positive": "default negative"}},
        "8": {"inputs": {"noise_seed": 1, "steps": 20, "cfg": 4.0}},
        "262": {"inputs": {"seed": 1}},
        "437": {"inputs": {"width": 512, "height": 512}},
        "20": {"inputs": {}},
        "285": {"inputs": {}},
        "777": {"inputs": {}},
    }
    path.write_text(json.dumps(workflow), encoding="utf-8")


def _write_upscale_workflow(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "1": {"inputs": {"image": "input.png"}},
                "552": {
                    "inputs": {
                        "resize_type.scale": 2.0,
                        "quality": "ULTRA",
                    }
                },
                "458": {"inputs": {}},
            }
        ),
        encoding="utf-8",
    )
    manifest_dir = path.parent / "manifests"
    manifest_dir.mkdir(exist_ok=True)
    (manifest_dir / f"{path.stem}.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile_id": "rtx_test",
                "display_name": "RTX Test",
                "workflow_file": path.name,
                "task_type": "upscale",
                "bindings": {
                    "input_image": {"node_id": "1", "input": "image"},
                    "upscale": {
                        "node_id": "552",
                        "scale_input": "resize_type.scale",
                        "quality_input": "quality",
                    },
                },
                "output_variants": {
                    "rtx": {
                        "preferred_node_ids": ["458"],
                        "prune_node_ids": [],
                    }
                },
                "default_output_variant": "rtx",
            }
        ),
        encoding="utf-8",
    )


class WorkflowRegistryTests(unittest.TestCase):
    """Verify discovery, selection, overrides, and boundary checks."""

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.workflow_dir = Path(self._temporary_directory.name) / "workflows"
        self.workflow_dir.mkdir()
        self.settings = PluginSettings(enable_upscale=True)
        self.registry = WorkflowRegistry(self.workflow_dir, self.settings)

    def test_discover_lists_only_sorted_direct_json_files(self) -> None:
        """Discovery should be deterministic and ignore unrelated paths."""
        _write_workflow(self.workflow_dir / "Zulu.json")
        _write_workflow(self.workflow_dir / "alpha.JSON")
        (self.workflow_dir / "notes.txt").write_text("ignore", encoding="utf-8")
        nested = self.workflow_dir / "nested"
        nested.mkdir()
        _write_workflow(nested / "hidden.json")

        entries = self.registry.list_workflows()

        self.assertEqual([entry.index for entry in entries], [1, 2])
        self.assertEqual(
            [entry.filename for entry in entries], ["alpha.JSON", "Zulu.json"]
        )
        self.assertTrue(all(entry.path.is_absolute() for entry in entries))

    def test_discover_refreshes_after_files_are_added(self) -> None:
        """Each discovery should observe workflows added at runtime."""
        _write_workflow(self.workflow_dir / "one.json")
        self.assertEqual(len(self.registry.discover()), 1)

        _write_workflow(self.workflow_dir / "two.json")

        self.assertEqual(len(self.registry.discover()), 2)

    def test_describe_marks_upscale_visible_but_not_selectable(self) -> None:
        _write_workflow(self.workflow_dir / "anima.json")
        _write_upscale_workflow(self.workflow_dir / "rtx.json")

        descriptors = self.registry.describe()

        by_name = {item.entry.filename: item for item in descriptors}
        self.assertTrue(by_name["anima.json"].selectable)
        self.assertEqual(by_name["anima.json"].task_type, "text_to_image")
        self.assertFalse(by_name["rtx.json"].selectable)
        self.assertEqual(by_name["rtx.json"].task_type, "upscale")
        self.assertIn("不能设为", by_name["rtx.json"].error)

    def test_select_filename_uses_fresh_exact_direct_child(self) -> None:
        _write_workflow(self.workflow_dir / "Anima.json")

        selection = self.registry.select_filename("anima.JSON")

        self.assertEqual(selection.entry.filename, "Anima.json")
        with self.assertRaises(WorkflowRegistryError):
            self.registry.select_filename("nested/anima.json")

    def test_select_uses_one_based_index_and_node_overrides(self) -> None:
        """Selection should copy settings and apply input/output node IDs."""
        _write_workflow(self.workflow_dir / "custom.json", prompt_node_id="999")

        selection = self.registry.select(
            1, input_node_id=" 999 ", output_node_id=" 777 "
        )
        workflow, _, preferred_outputs = selection.builder.build(
            GenerationOptions(prompt="1girl", seed=42)
        )

        self.assertEqual(selection.entry.filename, "custom.json")
        self.assertEqual(selection.settings.prompt_node_id, "999")
        self.assertEqual(selection.settings.output_node_ids, ["777"])
        self.assertEqual(workflow["999"]["inputs"]["positive"], "1girl")
        self.assertEqual(preferred_outputs, ["777"])
        self.assertEqual(self.settings.prompt_node_id, "210")
        self.assertNotEqual(self.settings.workflow_file, str(selection.entry.path))

    def test_create_builder_returns_ready_builder(self) -> None:
        """The convenience API should return a directly usable builder."""
        _write_workflow(self.workflow_dir / "default.json")

        builder = self.registry.create_builder(1, output_node_id="20")
        workflow, _, preferred_outputs = builder.build(
            GenerationOptions(prompt="cat", seed=7)
        )

        self.assertEqual(workflow["210"]["inputs"]["positive"], "cat")
        self.assertEqual(preferred_outputs, ["20"])

    def test_generic_text_node_does_not_require_anima_optional_nodes(self) -> None:
        """非 Anima 工作流只需文本输入节点即可完成热切换。"""
        path = self.workflow_dir / "generic.json"
        path.write_text(
            json.dumps(
                {
                    "6": {"inputs": {"text": "old prompt"}},
                    "9": {"inputs": {}},
                }
            ),
            encoding="utf-8",
        )

        selection = self.registry.select(1, input_node_id="6", output_node_id="9")
        workflow, _, preferred_outputs = selection.builder.build(
            GenerationOptions(prompt="new prompt", seed=7)
        )

        self.assertEqual(workflow["6"]["inputs"]["text"], "new prompt")
        self.assertEqual(preferred_outputs, ["9"])

    def test_select_rejects_invalid_indices_and_empty_node_ids(self) -> None:
        """Selection should reject non-1-based indices and blank overrides."""
        _write_workflow(self.workflow_dir / "only.json")

        for invalid_index in (0, 2, True):
            with self.subTest(index=invalid_index):
                with self.assertRaises(WorkflowRegistryError):
                    self.registry.select(invalid_index)
        with self.assertRaises(WorkflowRegistryError):
            self.registry.select(1, input_node_id="  ")
        with self.assertRaises(WorkflowRegistryError):
            self.registry.select(1, output_node_id="")

    def test_discover_ignores_resolved_paths_outside_directory(self) -> None:
        """A candidate resolving outside the trusted root must not be exposed."""
        outside_file = Path(self._temporary_directory.name) / "outside.json"
        _write_workflow(outside_file)

        with patch.object(Path, "iterdir", return_value=iter((outside_file,))):
            entries = self.registry.discover()

        self.assertEqual(entries, ())

    def test_missing_directory_raises_clear_error(self) -> None:
        """A nonexistent configured directory should fail explicitly."""
        registry = WorkflowRegistry(
            Path(self._temporary_directory.name) / "missing", self.settings
        )

        with self.assertRaises(WorkflowRegistryError):
            registry.discover()


if __name__ == "__main__":
    unittest.main()

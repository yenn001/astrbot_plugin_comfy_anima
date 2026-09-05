"""Regression tests for saved character preset authority over exact binding."""

import importlib
import types
import unittest

from ..models import LoraSelection
from ..services.lora_presets import (
    LoraPreset,
    PRESET_CATEGORY_CHARACTER,
)
from ._stubs import install_astrbot_stubs


class _Binding:
    def __init__(self, canonical: str) -> None:
        self.character_canonical = canonical
        self.copyright_canonical = "blue_archive"
        self.activation_terms = ()


class _Entry:
    def __init__(self, bindings) -> None:
        self.canonical_name = "达妮娅"
        self.identity_bindings = tuple(bindings)


class PresetAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_astrbot_stubs()
        cls.main = importlib.import_module("astrbot_plugin_comfy_anima.main")

    def _ambiguous_index(self):
        return types.SimpleNamespace(
            entries={
                "denia": _Entry(
                    [
                        _Binding("denia_(wuthering_waves)"),
                        _Binding("denia_(blue_archive)"),
                    ]
                )
            },
            canonical_lookup={},
            alias_lookup={},
        )

    def _plugin(self, presets, index):
        plugin = object.__new__(self.main.ComfyAnimaPlugin)
        plugin._lora_presets = types.SimpleNamespace(
            list_presets=lambda category: tuple(presets) if category == PRESET_CATEGORY_CHARACTER else ()
        )
        plugin._runtime_semantic_index = lambda: index
        return plugin

    def test_contract_preset_bypasses_exact_danbooru_binding_gate(self) -> None:
        preset = LoraPreset(
            name="达妮娅",
            category=PRESET_CATEGORY_CHARACTER,
            selections=(),
            identity_anchor="denia_(wuthering_waves)",
            required_trigger_terms=("denia",),
            contract_enabled=True,
        )
        plugin = self._plugin([preset], self._ambiguous_index())
        plan = types.SimpleNamespace(
            identity_required=True,
            requested_subject="达妮娅",
        )
        self.assertIsNone(
            plugin._resolve_subject_binding_gate(
                plan,
                subject_probe_available=True,
            )
        )

    def test_authorized_preset_lora_names_are_collected_for_gate_relaxation(
        self,
    ) -> None:
        preset = LoraPreset(
            name="达妮娅",
            category=PRESET_CATEGORY_CHARACTER,
            selections=(LoraSelection(name="denia.safetensors", strength=0.8),),
            identity_anchor="denia_(wuthering_waves)",
            required_trigger_terms=("denia",),
            contract_enabled=True,
        )
        plugin = self._plugin([preset], self._ambiguous_index())
        self.assertIn(
            "denia",
            plugin._authorized_character_preset_lora_names(),
        )

    def test_without_preset_ambiguous_binding_degrades_to_tag_flow(self) -> None:
        plugin = self._plugin([], self._ambiguous_index())
        plan = types.SimpleNamespace(
            identity_required=True,
            requested_subject="达妮娅",
        )
        self.assertIsNone(
            plugin._resolve_subject_binding_gate(
                plan,
                subject_probe_available=True,
            )
        )


if __name__ == "__main__":
    unittest.main()

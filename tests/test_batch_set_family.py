"""Tests for batch setting LoRA model-family compatibility mode."""

import tempfile
import unittest
from pathlib import Path

from ._stubs import install_astrbot_stubs
install_astrbot_stubs()

from ..services.lora_catalog import LoraRecord
from ..services.lora_semantic import LoraSemanticIndex


class BatchSetFamilyTests(unittest.IsolatedAsyncioTestCase):
    """验证 WebUI 批量与自动标记 29B 兼容模式。"""

    async def test_batch_set_family_auto_detect_29b(self) -> None:
        from ..main import ComfyAnimaPlugin

        async def async_records(*args, **kwargs):
            return records

        class DummyPlugin(ComfyAnimaPlugin):
            def __init__(self, semantic_index, semantic_index_path, records):
                self._semantic_index = semantic_index
                self._semantic_index_path = semantic_index_path
                self._test_records = records
                self._lora_catalog = type(
                    "Catalog",
                    (),
                    {
                        "refresh_for_operation": async_records,
                    },
                )()

            def _runtime_semantic_index(self):
                return self._semantic_index

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            index_path = tmp / "lora_semantic.json"
            semantic_index = LoraSemanticIndex()

            records = (
                LoraRecord(name="characters/denia.safetensors", sha256="1" * 64),
                LoraRecord(name="characters/denia_29b.safetensors", sha256="2" * 64),
                LoraRecord(name="29B/photo_background.safetensors", sha256="3" * 64),
                LoraRecord(name="styles/anime.safetensors", sha256="4" * 64),
            )

            main_obj = DummyPlugin(semantic_index, index_path, records)

            # 自动扫描并标记 29B 模型
            res = await main_obj.web_ui_batch_set_lora_family(
                {"auto_detect_29b": True}
            )

            self.assertTrue(res["success"])
            self.assertEqual(res["updated_count"], 2)
            self.assertIn("characters/denia_29b.safetensors", res["updated_names"])
            self.assertIn("29B/photo_background.safetensors", res["updated_names"])

            # 验证写入的 SemanticEntry
            entry_29b = semantic_index.entries.get(f"sha256:{'2' * 64}")
            self.assertIsNotNone(entry_29b)
            self.assertEqual(entry_29b.compatibility_mode, "native_29b")
            self.assertIn("anima_29b_40l", entry_29b.compatible_model_families)

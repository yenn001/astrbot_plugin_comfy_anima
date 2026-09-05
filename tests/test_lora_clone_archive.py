"""Zero-token fast clone tests for converted LoRA semantic archiving."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from ..services.lora_analysis import LoraAnalysisPipeline
from ..services.lora_detail import FileStatus, LoraDetailV2
from ..services.lora_semantic import (
    LoraSemanticIndex,
    SemanticEntry,
    SemanticFact,
    semantic_identity_key,
)
from ..services.task_store import TaskStore


class LoraCloneArchiveTests(unittest.IsolatedAsyncioTestCase):
    """验证 _29b 衍生 LoRA 在建档时直接从同源原版克隆档案，零调用 LLM。"""

    async def test_fast_clone_from_base_entry_without_llm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            index_path = tmp / "lora_semantic.json"
            db_path = tmp / "tasks.sqlite3"
            task_store = TaskStore(db_path)

            # 准备已有原版 Base LoRA 的已建档语义索引
            base_name = "characters/denia.safetensors"
            base_sha = "a" * 64
            base_entry = SemanticEntry(
                identity_key=semantic_identity_key(base_name, base_sha),
                canonical_name="characters/denia",
                sha256=base_sha,
                analysis_status="searchable",
                analysis_summary="达妮娅角色档案，来自官方数据集。",
                analysis_confidence=0.95,
                category=(SemanticFact("character", "observed"),),
                character_names=(SemanticFact("达妮娅", "observed"),),
                source_works=(SemanticFact("Anima", "observed"),),
                activation_terms=(SemanticFact("denia", "observed"),),
                aliases=(SemanticFact("dania", "observed"),),
            )
            semantic_index = LoraSemanticIndex(
                entries={base_entry.identity_key: base_entry}
            )

            pipeline = LoraAnalysisPipeline(
                semantic_index=semantic_index,
                semantic_index_path=index_path,
                task_store=task_store,
            )

            # 待建档的目标为 _29b 衍生版
            derived_name = "characters/denia_29b.safetensors"
            derived_sha = "b" * 64
            derived_detail = LoraDetailV2(
                asset_id=f"sha256:{derived_sha}",
                name=derived_name,
                file_name="denia_29b.safetensors",
                file_status=FileStatus(
                    loadable=True,
                    sha256=derived_sha,
                    file_size=1024,
                ),
            )

            llm_call_count = 0

            def dummy_llm(sys_prompt, user_prompt):
                nonlocal llm_call_count
                llm_call_count += 1
                return "{}"

            try:
                # 运行分析管线
                run_result = await pipeline.run(
                    [derived_detail],
                    dummy_llm,
                    run_id="test-run-1",
                )

                # 断言 1: LLM 回调被直接跳过，调用次数为 0 (零 Token 消耗)
                self.assertEqual(llm_call_count, 0)
                self.assertEqual(run_result.succeeded_count, 1)

                # 断言 2: 衍生 LoRA 成功生成语义档案且状态直接为 searchable
                derived_key = semantic_identity_key(derived_name, derived_sha)
                cloned = semantic_index.entries.get(derived_key)
                self.assertIsNotNone(cloned)
                self.assertEqual(cloned.analysis_status, "searchable")
                self.assertEqual(cloned.effective_category, "character")
                self.assertEqual(cloned.effective_values("character_names"), ("达妮娅",))
                self.assertEqual(cloned.effective_values("source_works"), ("Anima",))
                self.assertEqual(cloned.effective_values("activation_terms"), ("denia",))
                self.assertEqual(cloned.compatibility_mode, "native_29b")
                self.assertIn("anima_29b_40l", cloned.compatible_model_families)
                self.assertIn("同源快速克隆", cloned.analysis_summary)
            finally:
                task_store.close()

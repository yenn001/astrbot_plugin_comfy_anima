"""Civitai URL 下载、LoRA Manager 后处理与安全校验测试。"""

from __future__ import annotations

import unittest
from typing import Any, Optional
from unittest.mock import AsyncMock

from ..models import PluginSettings
from ..services.lora_downloader import (
    CivitaiUrlError,
    LoraDownloadError,
    LoraDownloadService,
    parse_civitai_model_url,
)


ALLOWED_HOSTS = [
    "civitai.com",
    "www.civitai.com",
    "civitai.red",
    "www.civitai.red",
]


class CivitaiUrlTests(unittest.TestCase):
    def test_accepts_official_model_page_and_version(self) -> None:
        reference = parse_civitai_model_url(
            "https://civitai.com/models/123456/example-name?modelVersionId=789012",
            ALLOWED_HOSTS,
        )
        self.assertEqual(reference.model_id, 123456)
        self.assertEqual(reference.version_id, 789012)

    def test_accepts_civitai_red_and_angle_brackets(self) -> None:
        reference = parse_civitai_model_url(
            "<https://civitai.red/models/123456>",
            ALLOWED_HOSTS,
        )
        self.assertEqual(reference.model_id, 123456)
        self.assertIsNone(reference.version_id)

    def test_rejects_ssrf_and_spoofed_hosts(self) -> None:
        invalid_urls = (
            "http://civitai.com/models/123",
            "https://civitai.com.evil.example/models/123",
            "https://user:password@civitai.com/models/123",
            "https://127.0.0.1/models/123",
            "file:///etc/passwd",
            "https://civitai.com:8443/models/123",
        )
        for url in invalid_urls:
            with self.subTest(url=url), self.assertRaises(CivitaiUrlError):
                parse_civitai_model_url(url, ALLOWED_HOSTS)

    def test_rejects_invalid_path_and_version(self) -> None:
        invalid_urls = (
            "https://civitai.com/api/download/models/123",
            "https://civitai.com/models/not-a-number",
            "https://civitai.com/models/123?modelVersionId=bad",
            "https://civitai.com/models/123?modelVersionId=1&modelVersionId=2",
        )
        for url in invalid_urls:
            with self.subTest(url=url), self.assertRaises(CivitaiUrlError):
                parse_civitai_model_url(url, ALLOWED_HOSTS)


class _FakeCatalog:
    def __init__(
        self,
        events: list[str],
        result: str = "清单已刷新",
        *,
        fail_on_call: Optional[int] = None,
    ):
        self.events = events
        self.result = result
        self.fail_on_call = fail_on_call
        self.calls = 0

    async def refresh_summary(self) -> str:
        self.calls += 1
        self.events.append("catalog")
        if self.calls == self.fail_on_call:
            raise LoraDownloadError("双源清单刷新失败")
        return self.result


class _FakeDownloader(LoraDownloadService):
    def __init__(
        self,
        *,
        versions: list[dict[str, Any]],
        item_pages: list[list[dict[str, Any]]],
        metadata_result: tuple[bool, str] = (True, "元数据已更新"),
        catalog: Optional[_FakeCatalog] = None,
        download_payload: Optional[dict[str, Any]] = None,
        scan_fail_on_call: Optional[int] = None,
        list_fail_on_call: Optional[int] = None,
    ):
        settings = PluginSettings.from_mapping(
            {
                "comfyui_url": "http://192.168.1.50:8188",
                "lora_download_allowed_hosts": ALLOWED_HOSTS,
            }
        )
        self.events: list[str] = []
        self.versions = versions
        self.item_pages = list(item_pages)
        self.metadata_result = metadata_result
        self.download_payload = download_payload or {"success": True}
        self.scan_fail_on_call = scan_fail_on_call
        self.list_fail_on_call = list_fail_on_call
        self.scan_calls = 0
        self.list_calls = 0
        self.metadata_paths: list[str] = []
        super().__init__(settings, catalog or _FakeCatalog(self.events))

    async def _fetch_versions(self, model_id: int) -> list[dict[str, Any]]:
        self.events.append("versions")
        return self.versions

    async def _fetch_manager_items(self) -> list[dict[str, Any]]:
        self.list_calls += 1
        self.events.append("list")
        if self.list_calls == self.list_fail_on_call:
            raise LoraDownloadError("Manager 清单读取失败")
        if not self.item_pages:
            return []
        return self.item_pages.pop(0)

    async def _post_download(
        self,
        model_id: int,
        version_id: int,
        download_id: str,
    ) -> dict[str, Any]:
        self.events.append("download-complete")
        return {**self.download_payload, "download_id": download_id}

    async def _scan_manager(self) -> None:
        self.scan_calls += 1
        self.events.append("scan")
        if self.scan_calls == self.scan_fail_on_call:
            raise LoraDownloadError("Manager 扫描失败")

    async def _fetch_civitai_metadata(self, file_path: str) -> tuple[bool, str]:
        self.events.append("metadata")
        self.metadata_paths.append(file_path)
        return self.metadata_result


def _version(version_id: int, created_at: str, name: str) -> dict[str, Any]:
    return {
        "id": version_id,
        "name": name,
        "createdAt": created_at,
        "files": [
            {
                "name": f"model-{version_id}.safetensors",
                "hashes": {"SHA256": f"HASH-{version_id}"},
            }
        ],
    }


def _item(model_id: int, version_id: int) -> dict[str, Any]:
    return {
        "file_name": f"model-{version_id}",
        "file_path": f"E:/ComfyUI/models/loras/model-{version_id}.safetensors",
        "sha256": f"HASH-{version_id}",
        "civitai": {"id": version_id, "modelId": model_id},
    }


class LoraDownloadFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_latest_version_downloads_before_metadata_and_refresh(self) -> None:
        downloader = _FakeDownloader(
            versions=[
                _version(10, "2026-01-01T00:00:00Z", "旧版"),
                _version(20, "2026-06-01T00:00:00Z", "新版"),
            ],
            item_pages=[[], [_item(123, 20)]],
        )
        result = await downloader.download_from_url(
            "https://civitai.com/models/123/example"
        )
        self.assertTrue(result.downloaded)
        self.assertTrue(result.auto_selected_version)
        self.assertEqual(result.version_id, 20)
        self.assertEqual(
            downloader.events,
            [
                "catalog",
                "scan",
                "versions",
                "list",
                "download-complete",
                "scan",
                "list",
                "metadata",
                "catalog",
            ],
        )

    async def test_metadata_failure_is_partial_success_and_catalog_still_refreshes(
        self,
    ) -> None:
        downloader = _FakeDownloader(
            versions=[_version(20, "2026-06-01T00:00:00Z", "新版")],
            item_pages=[[], [_item(123, 20)]],
            metadata_result=(False, "Civitai 查询失败"),
        )
        result = await downloader.download_from_url(
            "https://civitai.com/models/123?modelVersionId=20"
        )
        self.assertTrue(result.downloaded)
        self.assertFalse(result.metadata_success)
        self.assertTrue(result.catalog_success)
        self.assertEqual(downloader.events[-2:], ["metadata", "catalog"])

    async def test_existing_version_skips_download_but_refreshes_metadata(self) -> None:
        downloader = _FakeDownloader(
            versions=[_version(20, "2026-06-01T00:00:00Z", "新版")],
            item_pages=[[_item(123, 20)]],
        )
        result = await downloader.download_from_url(
            "https://civitai.com/models/123?modelVersionId=20"
        )
        self.assertFalse(result.downloaded)
        self.assertNotIn("download-complete", downloader.events)
        self.assertEqual(
            downloader.events,
            ["catalog", "scan", "versions", "list", "metadata", "catalog"],
        )

    async def test_download_stops_when_fresh_dual_source_catalog_fails(self) -> None:
        downloader = _FakeDownloader(
            versions=[_version(20, "2026-06-01T00:00:00Z", "新版")],
            item_pages=[[]],
        )
        downloader._catalog = _FakeCatalog(
            downloader.events,
            fail_on_call=1,
        )

        with self.assertRaises(LoraDownloadError) as raised:
            await downloader.download_from_url(
                "https://civitai.com/models/123?modelVersionId=20"
            )

        self.assertIn("下载前刷新", raised.exception.user_message)
        self.assertEqual(downloader.events, ["catalog"])

    async def test_post_download_scan_failure_is_not_ready(self) -> None:
        downloader = _FakeDownloader(
            versions=[_version(20, "2026-06-01T00:00:00Z", "新版")],
            item_pages=[[]],
            scan_fail_on_call=2,
        )

        with self.assertRaises(LoraDownloadError) as raised:
            await downloader.download_from_url(
                "https://civitai.com/models/123?modelVersionId=20"
            )

        self.assertIn("当前未就绪", raised.exception.user_message)
        self.assertNotIn("metadata", downloader.events)
        self.assertEqual(
            downloader.events,
            ["catalog", "scan", "versions", "list", "download-complete", "scan"],
        )

    async def test_post_download_list_failure_is_not_ready(self) -> None:
        downloader = _FakeDownloader(
            versions=[_version(20, "2026-06-01T00:00:00Z", "新版")],
            item_pages=[[]],
            list_fail_on_call=2,
        )

        with self.assertRaises(LoraDownloadError) as raised:
            await downloader.download_from_url(
                "https://civitai.com/models/123?modelVersionId=20"
            )

        self.assertIn("当前未就绪", raised.exception.user_message)
        self.assertNotIn("metadata", downloader.events)

    async def test_download_response_file_path_cannot_bypass_fresh_list(self) -> None:
        raw_path = "E:/ComfyUI/models/loras/unverified.safetensors"
        downloader = _FakeDownloader(
            versions=[_version(20, "2026-06-01T00:00:00Z", "新版")],
            item_pages=[[], []],
            download_payload={"success": True, "file_path": raw_path},
        )

        with self.assertRaises(LoraDownloadError) as raised:
            await downloader.download_from_url(
                "https://civitai.com/models/123?modelVersionId=20"
            )

        self.assertIn("未找到唯一精确文件", raised.exception.user_message)
        self.assertEqual(downloader.metadata_paths, [])

    async def test_success_uses_only_unique_exact_refreshed_file(self) -> None:
        target = _item(123, 20)
        downloader = _FakeDownloader(
            versions=[_version(20, "2026-06-01T00:00:00Z", "新版")],
            item_pages=[[], [_item(999, 77), target]],
        )

        result = await downloader.download_from_url(
            "https://civitai.com/models/123?modelVersionId=20"
        )

        self.assertTrue(result.downloaded)
        self.assertEqual(result.file_path, target["file_path"])
        self.assertEqual(downloader.metadata_paths, [target["file_path"]])

    async def test_ambiguous_exact_files_stop_before_metadata(self) -> None:
        first = _item(123, 20)
        second = {
            **_item(123, 20),
            "file_name": "duplicate-model-20",
            "file_path": "E:/ComfyUI/models/loras/duplicate-model-20.safetensors",
        }
        downloader = _FakeDownloader(
            versions=[_version(20, "2026-06-01T00:00:00Z", "新版")],
            item_pages=[[first, second]],
        )

        with self.assertRaises(LoraDownloadError) as raised:
            await downloader.download_from_url(
                "https://civitai.com/models/123?modelVersionId=20"
            )

        self.assertIn("多个精确匹配文件", raised.exception.user_message)
        self.assertNotIn("metadata", downloader.events)
        self.assertNotIn("download-complete", downloader.events)

    async def test_download_payload_uses_manager_default_paths(self) -> None:
        settings = PluginSettings.from_mapping(
            {"comfyui_url": "http://192.168.1.50:8188"}
        )
        service = LoraDownloadService(settings)
        service._request_json = AsyncMock(return_value={"success": True})
        await service._post_download(123, 456, "download-id")
        kwargs = service._request_json.await_args.kwargs
        self.assertEqual(
            kwargs["payload"],
            {
                "model_id": 123,
                "model_version_id": 456,
                "model_root": "",
                "relative_path": "",
                "use_default_paths": True,
                "download_id": "download-id",
            },
        )

    async def test_public_single_metadata_fetch_reuses_manager_endpoint(self) -> None:
        settings = PluginSettings.from_mapping(
            {"comfyui_url": "http://192.168.1.50:8188"}
        )
        service = LoraDownloadService(settings)
        service._request_json = AsyncMock(
            return_value={"success": True, "metadata": {"name": "Denia"}}
        )

        success, message = await service.fetch_civitai_metadata(
            "E:/loras/denia.safetensors"
        )

        self.assertTrue(success)
        self.assertIn("Civitai", message)
        self.assertTrue(
            service._request_json.await_args.args[1].endswith(
                "/api/lm/loras/fetch-civitai"
            )
        )

    async def test_bulk_metadata_fetch_uses_native_manager_operation(self) -> None:
        settings = PluginSettings.from_mapping(
            {"comfyui_url": "http://192.168.1.50:8188"}
        )
        service = LoraDownloadService(settings)
        service._request_json = AsyncMock(
            return_value={"success": True, "processed": 4, "updated": 3}
        )

        result = await service.fetch_all_civitai_metadata()

        self.assertEqual(result["updated"], 3)
        self.assertTrue(
            service._request_json.await_args.args[1].endswith(
                "/api/lm/loras/fetch-all-civitai"
            )
        )


if __name__ == "__main__":
    unittest.main()

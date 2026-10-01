"""WebUI status payload for 307 prompt catalog and runtime probe phases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class WebUiStatus:
    target_version: str
    prompt_catalog: tuple[str, ...]
    prompt_contract_version: str
    runtime_probe_phase: str
    delivery_receipt_mode: str
    pending_items: tuple[str, ...]


def build_webui_status(
    *,
    target_version: str,
    prompt_catalog: tuple[str, ...],
    prompt_contract_version: str,
    runtime_probe_phase: str = "pre-stage1",
    delivery_receipt_mode: str = "unknown",
    pending_items: tuple[str, ...] = (),
) -> Mapping[str, Any]:
    """Return the JSON-safe status shown by the plugin WebUI page."""

    return {
        "target_version": str(target_version),
        "prompt_catalog": list(prompt_catalog),
        "prompt_contract_version": str(prompt_contract_version),
        "runtime_probe_phase": str(runtime_probe_phase),
        "delivery_receipt_mode": str(delivery_receipt_mode),
        "pending_items": list(pending_items),
    }


__all__ = ["WebUiStatus", "build_webui_status"]

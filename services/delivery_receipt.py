"""Delivery receipt provider seam.

2.1.307 ships with the Null provider because the aiocqhttp event API returns
``None`` from ``event.send()`` and exposes no message_id. The SENT branch is
therefore intentionally unreachable in this release; every send is recorded
as UNKNOWN and the task stays ``partial``. Future providers must return a
real message_id before the delivery ledger may move to SENT.
"""

from __future__ import annotations

from typing import Any, Protocol


class DeliveryReceiptProvider(Protocol):
    def capture_send(
        self,
        event: Any,
        *,
        platform: str = "",
    ) -> str:
        """Return a verified message_id or an empty string."""


class NullDeliveryReceiptProvider:
    """Permanent UNKNOWN downgrade for 2.1.307."""

    def capture_send(
        self,
        event: Any,
        *,
        platform: str = "",
    ) -> str:
        return ""


def get_delivery_receipt_provider(settings: Any = None) -> DeliveryReceiptProvider:
    """Return the configured receipt provider; only Null exists in 307."""

    return NullDeliveryReceiptProvider()


__all__ = [
    "DeliveryReceiptProvider",
    "NullDeliveryReceiptProvider",
    "get_delivery_receipt_provider",
]

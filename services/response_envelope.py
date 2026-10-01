"""Response envelope, multi-bundle ledger and delivery receipt for one event.

The ledger lives in ``event`` extras under one key. Bundle attachment is the
only mutation path and validates envelope ownership first. Image/draw bundles
support multiple entries; the text bundle remains single.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Callable

EXTRAS_KEY = "astrbot_plugin_comfy_anima:response_envelope_v1"


class BundleKind(str, Enum):
    TEXT = "text"
    DRAW = "draw"
    IMAGE = "image"


class BundleState(str, Enum):
    CREATED = "created"
    ATTACHED = "attached"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    DELIVERED = "delivered"
    FAILED = "failed"


class ReceiptState(str, Enum):
    UNKNOWN = "unknown"
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class BundleOwnershipError(RuntimeError):
    """Raised when a bundle is mounted onto a different envelope."""


@dataclass(frozen=True)
class DeliveryReceipt:
    """Per-bundle delivery receipt; message_id is authoritative evidence."""

    bundle_id: str
    status: ReceiptState = ReceiptState.UNKNOWN
    message_id: str = ""
    platform: str = ""
    sent_at: float = 0.0
    attempt_count: int = 0
    last_error: str = ""
    run_id: str = ""
    output_path: str = ""
    output_sha256: str = ""

    @property
    def status_text(self) -> str:
        """Return the status as its wire/string value for old consumers."""
        return self.status.value

    @property
    def has_verified_send(self) -> bool:
        return self.status == ReceiptState.SENT and bool(self.message_id)

    def attach_output(
        self,
        *,
        run_id: str,
        output_path: str,
        output_sha256: str,
    ) -> "DeliveryReceipt":
        return replace(
            self,
            run_id=str(run_id),
            output_path=str(output_path),
            output_sha256=str(output_sha256),
        )


@dataclass
class ResponseBundle:
    kind: BundleKind
    bundle_id: str = ""
    state: str = BundleState.CREATED.value
    bundle_run_id: str = ""
    payload: Any = None
    receipt: DeliveryReceipt | None = None
    response_id: str = ""
    parent_run_id: str = ""


@dataclass
class ResponseEnvelope:
    response_id: str
    parent_run_id: str
    text_bundle: ResponseBundle | None = None
    draw_bundles: list[ResponseBundle] = field(default_factory=list)
    image_bundles: list[ResponseBundle] = field(default_factory=list)

    @property
    def draw_bundle(self) -> ResponseBundle | None:
        return self.draw_bundles[0] if self.draw_bundles else None

    @property
    def image_bundle(self) -> ResponseBundle | None:
        return self.image_bundles[0] if self.image_bundles else None


def _new_id() -> str:
    return uuid.uuid4().hex


class BundleLedger:
    """Read-only envelope view plus the single validated attach entry."""

    def __init__(self, event: Any) -> None:
        self._event = event

    @classmethod
    def for_event(cls, event: Any) -> "BundleLedger":
        return cls(event)

    def _envelope(self) -> ResponseEnvelope | None:
        return self._event.get_extra(EXTRAS_KEY, None)

    def envelope(self) -> ResponseEnvelope | None:
        """Return the current envelope without mutating it."""

        return self._envelope()

    def _write(self, envelope: ResponseEnvelope) -> None:
        self._event.set_extra(EXTRAS_KEY, envelope)

    def _all_bundles(self, envelope: ResponseEnvelope) -> list[ResponseBundle]:
        bundles: list[ResponseBundle] = []
        if envelope.text_bundle is not None:
            bundles.append(envelope.text_bundle)
        bundles.extend(envelope.draw_bundles)
        bundles.extend(envelope.image_bundles)
        return bundles

    def ensure_envelope(self, *, allocate_run_id: Callable[[], str]) -> ResponseEnvelope:
        existing = self._envelope()
        if existing is not None:
            return existing
        envelope = ResponseEnvelope(
            response_id=_new_id(),
            parent_run_id=allocate_run_id(),
        )
        self._write(envelope)
        return envelope

    def attach_bundle(self, bundle: ResponseBundle) -> ResponseBundle:
        """Validate ownership and mount a bundle; reject cross-envelope IDs."""

        envelope = self._envelope()
        if envelope is None:
            raise BundleOwnershipError("envelope does not exist")
        if bundle.response_id != envelope.response_id:
            raise BundleOwnershipError("bundle.response_id does not match envelope")
        if bundle.parent_run_id != envelope.parent_run_id:
            raise BundleOwnershipError("bundle.parent_run_id does not match envelope")
        if not bundle.bundle_id:
            bundle.bundle_id = _new_id()
        existing_ids = {item.bundle_id for item in self._all_bundles(envelope)}
        if bundle.bundle_id in existing_ids:
            raise BundleOwnershipError("duplicate bundle_id in envelope")
        if bundle.kind is BundleKind.TEXT:
            if envelope.text_bundle is not None:
                raise BundleOwnershipError("text bundle slot already occupied")
            envelope.text_bundle = bundle
        elif bundle.kind is BundleKind.DRAW:
            if envelope.draw_bundles:
                raise BundleOwnershipError(
                    "single bundle mode: a draw bundle already exists"
                )
            envelope.draw_bundles.append(bundle)
        elif bundle.kind is BundleKind.IMAGE:
            if envelope.image_bundles:
                raise BundleOwnershipError(
                    "single bundle mode: an image bundle already exists"
                )
            envelope.image_bundles.append(bundle)
        else:
            raise BundleOwnershipError(f"unsupported bundle kind: {bundle.kind}")
        bundle.state = BundleState.ATTACHED.value
        self._write(envelope)
        return bundle

    def new_bundle(self, kind: BundleKind, *, bundle_run_id: str = "", payload: Any = None) -> ResponseBundle:
        envelope = self._envelope()
        if envelope is None:
            raise BundleOwnershipError("envelope does not exist")
        bundle = ResponseBundle(
            bundle_id=_new_id(),
            kind=kind,
            bundle_run_id=bundle_run_id,
            payload=payload,
            response_id=envelope.response_id,
            parent_run_id=envelope.parent_run_id,
        )
        return self.attach_bundle(bundle)

    def append_text(self, text: str) -> str:
        envelope = self._envelope()
        if envelope is None or envelope.text_bundle is None:
            raise BundleOwnershipError("text bundle does not exist")
        if envelope.text_bundle.payload is None:
            envelope.text_bundle.payload = str(text)
        else:
            envelope.text_bundle.payload = str(envelope.text_bundle.payload) + str(text)
        self._write(envelope)
        return envelope.text_bundle.payload

    def merged_text(self) -> str:
        envelope = self._envelope()
        if envelope is None or envelope.text_bundle is None:
            return ""
        return str(envelope.text_bundle.payload or "")

    def mark(self, bundle_id: str, state: BundleState | str) -> None:
        envelope = self._envelope()
        if envelope is None:
            raise BundleOwnershipError("envelope does not exist")
        for bundle in self._all_bundles(envelope):
            if bundle.bundle_id == bundle_id:
                bundle.state = str(state)
                self._write(envelope)
                return
        raise BundleOwnershipError("unknown bundle_id")

    def attach_output(
        self,
        bundle_id: str,
        *,
        run_id: str,
        output_path: str,
        output_sha256: str,
    ) -> DeliveryReceipt:
        """Attach output evidence to one bundle's receipt."""

        envelope = self._envelope()
        if envelope is None:
            raise BundleOwnershipError("envelope does not exist")
        for bundle in self._all_bundles(envelope):
            if bundle.bundle_id != bundle_id:
                continue
            if not bundle.bundle_run_id:
                bundle.bundle_run_id = str(run_id)
            if str(run_id) != bundle.bundle_run_id:
                raise BundleOwnershipError(
                    "receipt run_id does not match bundle_run_id"
                )
            if bundle.receipt is None:
                bundle.receipt = DeliveryReceipt(bundle_id=bundle_id)
            bundle.receipt = bundle.receipt.attach_output(
                run_id=bundle.bundle_run_id,
                output_path=output_path,
                output_sha256=output_sha256,
            )
            self._write(envelope)
            return bundle.receipt
        raise BundleOwnershipError("unknown bundle_id")

    def mark_send_attempt(
        self,
        bundle_id: str,
        *,
        message_id: str = "",
        platform: str = "",
        error: str = "",
    ) -> DeliveryReceipt:
        """Update a receipt; SENT is impossible without a real message_id."""

        envelope = self._envelope()
        if envelope is None:
            raise BundleOwnershipError("envelope does not exist")
        for bundle in self._all_bundles(envelope):
            if bundle.bundle_id != bundle_id:
                continue
            if bundle.receipt is None:
                bundle.receipt = DeliveryReceipt(bundle_id=bundle_id)
            receipt = bundle.receipt
            next_status = receipt.status
            next_message_id = receipt.message_id
            next_sent_at = receipt.sent_at
            next_last_error = receipt.last_error
            if error:
                next_status = ReceiptState.FAILED
                next_last_error = str(error)[:500]
            elif str(message_id or "").strip():
                next_status = ReceiptState.SENT
                next_message_id = str(message_id).strip()
                next_sent_at = time.time()
            else:
                next_status = ReceiptState.UNKNOWN
            bundle.receipt = replace(
                receipt,
                attempt_count=receipt.attempt_count + 1,
                platform=platform or receipt.platform,
                last_error=next_last_error,
                status=next_status,
                message_id=next_message_id,
                sent_at=next_sent_at,
            )
            self._write(envelope)
            return bundle.receipt
        raise BundleOwnershipError("unknown bundle_id")

    def terminal(self) -> bool:
        envelope = self._envelope()
        if envelope is None:
            return False
        for bundle in self._all_bundles(envelope):
            if bundle.state not in {
                BundleState.DELIVERED.value,
                BundleState.FAILED.value,
                BundleState.COMPLETED.value,
            }:
                return False
        return True


__all__ = [
    "BundleKind",
    "BundleLedger",
    "BundleOwnershipError",
    "BundleState",
    "DeliveryReceipt",
    "EXTRAS_KEY",
    "ReceiptState",
    "ResponseBundle",
    "ResponseEnvelope",
]

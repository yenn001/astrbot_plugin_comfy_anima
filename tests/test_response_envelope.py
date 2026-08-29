"""Response envelope and delivery receipt ledger tests."""

import unittest

from ..services.response_envelope import (
    BundleKind,
    BundleLedger,
    BundleOwnershipError,
    BundleState,
    ReceiptState,
    ResponseBundle,
)


class _Event:
    def __init__(self):
        self._extras = {}

    def get_extra(self, key, default=None):
        return self._extras.get(key, default)

    def set_extra(self, key, value):
        self._extras[key] = value


class ResponseEnvelopeTests(unittest.TestCase):
    def test_ensure_envelope_allocates_run_id_once(self) -> None:
        event = _Event()
        ledger = BundleLedger.for_event(event)
        first = ledger.ensure_envelope(allocate_run_id=lambda: "run-1")
        second = ledger.ensure_envelope(allocate_run_id=lambda: "run-2")
        self.assertIs(first, second)
        self.assertEqual(first.parent_run_id, "run-1")
        self.assertTrue(first.response_id)

    def test_attach_validates_cross_envelope_ownership(self) -> None:
        event = _Event()
        envelope = BundleLedger.for_event(event).ensure_envelope(
            allocate_run_id=lambda: "run-1"
        )
        bundle = ResponseBundle(
            bundle_id="b1",
            kind=BundleKind.TEXT,
            response_id="other",
            parent_run_id="run-1",
        )
        with self.assertRaises(BundleOwnershipError):
            BundleLedger.for_event(event).attach_bundle(bundle)
        bundle = ResponseBundle(
            bundle_id="b1",
            kind=BundleKind.TEXT,
            response_id=envelope.response_id,
            parent_run_id="other",
        )
        with self.assertRaises(BundleOwnershipError):
            BundleLedger.for_event(event).attach_bundle(bundle)

    def test_attach_owns_bundle_and_rejects_duplicate_slot(self) -> None:
        event = _Event()
        ledger = BundleLedger.for_event(event)
        envelope = ledger.ensure_envelope(allocate_run_id=lambda: "run-1")
        text = ResponseBundle(
            kind=BundleKind.TEXT,
            response_id=envelope.response_id,
            parent_run_id=envelope.parent_run_id,
        )
        ledger.attach_bundle(text)
        self.assertEqual(text.state, BundleState.ATTACHED.value)
        second = ResponseBundle(
            kind=BundleKind.TEXT,
            response_id=envelope.response_id,
            parent_run_id=envelope.parent_run_id,
        )
        with self.assertRaises(BundleOwnershipError):
            ledger.attach_bundle(second)

    def test_append_and_merged_text(self) -> None:
        event = _Event()
        ledger = BundleLedger.for_event(event)
        envelope = ledger.ensure_envelope(allocate_run_id=lambda: "run-1")
        ledger.attach_bundle(
            ResponseBundle(
                kind=BundleKind.TEXT,
                response_id=envelope.response_id,
                parent_run_id=envelope.parent_run_id,
            )
        )
        ledger.append_text("你好")
        ledger.append_text("，主人")
        self.assertEqual(ledger.merged_text(), "你好，主人")

    def test_mark_and_terminal(self) -> None:
        event = _Event()
        ledger = BundleLedger.for_event(event)
        ledger.ensure_envelope(allocate_run_id=lambda: "run-1")
        draw = ledger.new_bundle(BundleKind.DRAW, bundle_run_id="comfy-run")
        ledger.mark(draw.bundle_id, BundleState.COMPLETED)
        self.assertFalse(ledger.terminal())
        ledger.new_bundle(BundleKind.TEXT)
        ledger.mark(draw.bundle_id, BundleState.DELIVERED)
        self.assertFalse(ledger.terminal())

    def test_sent_requires_real_message_id(self) -> None:
        event = _Event()
        ledger = BundleLedger.for_event(event)
        ledger.ensure_envelope(allocate_run_id=lambda: "run-1")
        bundle = ledger.new_bundle(BundleKind.IMAGE, bundle_run_id="comfy-run")
        receipt = ledger.mark_send_attempt(bundle.bundle_id)
        self.assertEqual(receipt.state, ReceiptState.UNKNOWN.value)
        self.assertFalse(receipt.has_verified_send)
        receipt = ledger.mark_send_attempt(bundle.bundle_id, message_id="msg-123")
        self.assertEqual(receipt.state, ReceiptState.SENT.value)
        self.assertTrue(receipt.has_verified_send)

    def test_failed_send_attempt_is_recorded(self) -> None:
        event = _Event()
        ledger = BundleLedger.for_event(event)
        ledger.ensure_envelope(allocate_run_id=lambda: "run-1")
        bundle = ledger.new_bundle(BundleKind.IMAGE, bundle_run_id="comfy-run")
        receipt = ledger.mark_send_attempt(
            bundle.bundle_id, error="adapter exploded"
        )
        self.assertEqual(receipt.state, ReceiptState.FAILED.value)
        self.assertEqual(receipt.attempt_count, 1)
        self.assertEqual(receipt.last_error, "adapter exploded")


    def test_multiple_bundles_share_parent_run_id(self) -> None:
        event = _Event()
        ledger = BundleLedger.for_event(event)
        envelope = ledger.ensure_envelope(allocate_run_id=lambda: "run-1")
        text = ledger.new_bundle(BundleKind.TEXT)
        draw = ledger.new_bundle(BundleKind.DRAW, bundle_run_id="comfy-run")
        image = ledger.new_bundle(BundleKind.IMAGE, bundle_run_id="comfy-run")
        self.assertEqual(text.parent_run_id, "run-1")
        self.assertEqual(draw.parent_run_id, "run-1")
        self.assertEqual(image.parent_run_id, "run-1")
        self.assertIs(envelope.text_bundle, text)
        self.assertIs(envelope.draw_bundle, draw)
        self.assertIs(envelope.image_bundle, image)
        self.assertFalse(ledger.terminal())

    def test_receipt_carries_output_evidence(self) -> None:
        event = _Event()
        ledger = BundleLedger.for_event(event)
        ledger.ensure_envelope(allocate_run_id=lambda: "run-1")
        bundle = ledger.new_bundle(BundleKind.IMAGE, bundle_run_id="run-1")
        ledger.mark_send_attempt(bundle.bundle_id)
        receipt = ledger.mark_send_attempt(bundle.bundle_id, message_id="msg-9")
        receipt.attach_output(
            run_id="run-1",
            output_path="/out/a.png",
            output_sha256="abc123",
        )
        self.assertEqual(receipt.status, ReceiptState.SENT.value)
        self.assertEqual(receipt.run_id, "run-1")
        self.assertEqual(receipt.output_path, "/out/a.png")
        self.assertEqual(receipt.output_sha256, "abc123")

    def test_attach_output_rejects_cross_run_id(self) -> None:
        event = _Event()
        ledger = BundleLedger.for_event(event)
        ledger.ensure_envelope(allocate_run_id=lambda: "run-1")
        bundle = ledger.new_bundle(BundleKind.IMAGE, bundle_run_id="run-1")
        with self.assertRaises(BundleOwnershipError):
            ledger.attach_output(
                bundle.bundle_id,
                run_id="run-2",
                output_path="/out/a.png",
                output_sha256="abc",
            )

    def test_second_image_bundle_is_rejected_in_single_bundle_mode(self) -> None:
        event = _Event()
        ledger = BundleLedger.for_event(event)
        ledger.ensure_envelope(allocate_run_id=lambda: "run-1")
        first = ledger.new_bundle(BundleKind.IMAGE, bundle_run_id="run-1")
        with self.assertRaises(BundleOwnershipError):
            ledger.new_bundle(BundleKind.IMAGE, bundle_run_id="run-1")
        envelope = ledger.envelope()
        assert envelope is not None
        self.assertEqual(len(envelope.image_bundles), 1)
        self.assertIs(envelope.image_bundle, first)


if __name__ == "__main__":
    unittest.main()

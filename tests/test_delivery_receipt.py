"""Delivery receipt provider seam tests."""

import unittest

from ..services.delivery_receipt import get_delivery_receipt_provider


class DeliveryReceiptProviderTests(unittest.TestCase):
    def test_307_provider_returns_empty_message_id(self) -> None:
        provider = get_delivery_receipt_provider()
        self.assertEqual(provider.capture_send(object(), platform="qq"), "")


if __name__ == "__main__":
    unittest.main()

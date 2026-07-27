import json
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app import main


class PaymentServiceTests(unittest.IsolatedAsyncioTestCase):
    def make_request(self) -> main.PaymentRequest:
        return main.PaymentRequest(
            reservation_id=uuid4(),
            user_id=101,
            amount=20.0,
        )

    def test_fixed_delay_has_priority(self):
        with (
            patch.object(main, "PAYMENT_DELAY_SECONDS", 20.0),
            patch.object(main, "PAYMENT_MIN_DELAY_MS", 100.0),
            patch.object(main, "PAYMENT_MAX_DELAY_MS", 800.0),
        ):
            delay, source = main.select_payment_delay()

        self.assertEqual(delay, 20.0)
        self.assertEqual(source, "fixed")

    def test_random_delay_stays_inside_range(self):
        with (
            patch.object(main, "PAYMENT_DELAY_SECONDS", 0.0),
            patch.object(main, "PAYMENT_MIN_DELAY_MS", 100.0),
            patch.object(main, "PAYMENT_MAX_DELAY_MS", 800.0),
            patch.object(main.random, "uniform", return_value=450.0),
        ):
            delay, source = main.select_payment_delay()

        self.assertEqual(delay, 0.45)
        self.assertEqual(source, "random")

    async def test_normal_payment_is_approved(self):
        with (
            patch.object(main, "PAYMENT_DELAY_SECONDS", 0.0),
            patch.object(main, "PAYMENT_MIN_DELAY_MS", 0.0),
            patch.object(main, "PAYMENT_MAX_DELAY_MS", 0.0),
            patch.object(main, "PAYMENT_FAILURE_MODE", "none"),
            patch.object(main, "PAYMENT_FAILURE_RATE", 0.0),
        ):
            result = await main.process_payment(self.make_request())

        self.assertEqual(result["status"], "APPROVED")
        self.assertIn("transaction_id", result)

    async def test_forced_rejection_returns_402(self):
        with (
            patch.object(main, "PAYMENT_DELAY_SECONDS", 0.0),
            patch.object(main, "PAYMENT_MIN_DELAY_MS", 0.0),
            patch.object(main, "PAYMENT_MAX_DELAY_MS", 0.0),
            patch.object(main, "PAYMENT_FAILURE_MODE", "reject"),
            patch.object(main, "PAYMENT_FAILURE_RATE", 0.0),
        ):
            result = await main.process_payment(self.make_request())

        self.assertEqual(result.status_code, 402)
        self.assertEqual(json.loads(result.body)["status"], "REJECTED")

    async def test_random_failure_rate_can_reject(self):
        with (
            patch.object(main, "PAYMENT_DELAY_SECONDS", 0.0),
            patch.object(main, "PAYMENT_MIN_DELAY_MS", 0.0),
            patch.object(main, "PAYMENT_MAX_DELAY_MS", 0.0),
            patch.object(main, "PAYMENT_FAILURE_MODE", "none"),
            patch.object(main, "PAYMENT_FAILURE_RATE", 0.05),
            patch.object(main.random, "random", return_value=0.01),
        ):
            result = await main.process_payment(self.make_request())

        self.assertEqual(result.status_code, 402)
        self.assertEqual(json.loads(result.body)["status"], "REJECTED")

    async def test_configured_delay_is_asynchronous(self):
        with (
            patch.object(main, "PAYMENT_DELAY_SECONDS", 20.0),
            patch.object(main, "PAYMENT_FAILURE_MODE", "none"),
            patch.object(main, "PAYMENT_FAILURE_RATE", 0.0),
            patch.object(main.asyncio, "sleep", new=AsyncMock()) as sleep_mock,
        ):
            result = await main.process_payment(self.make_request())

        sleep_mock.assert_awaited_once_with(20.0)
        self.assertEqual(result["status"], "APPROVED")


if __name__ == "__main__":
    unittest.main()

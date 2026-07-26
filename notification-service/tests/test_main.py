import json
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app import main


class NotificationServiceTests(unittest.IsolatedAsyncioTestCase):
    def make_request(self) -> main.NotificationRequest:
        return main.NotificationRequest(
            reservation_id=uuid4(),
            user_id=101,
            message="Su reserva fue confirmada.",
        )

    def test_fixed_delay_has_priority(self):
        with (
            patch.object(main, "NOTIFICATION_DELAY_SECONDS", 10.0),
            patch.object(main, "NOTIFICATION_MIN_DELAY_MS", 50.0),
            patch.object(main, "NOTIFICATION_MAX_DELAY_MS", 500.0),
        ):
            delay, source = main.select_notification_delay()

        self.assertEqual(delay, 10.0)
        self.assertEqual(source, "fixed")

    def test_random_delay_stays_inside_range(self):
        with (
            patch.object(main, "NOTIFICATION_DELAY_SECONDS", 0.0),
            patch.object(main, "NOTIFICATION_MIN_DELAY_MS", 50.0),
            patch.object(main, "NOTIFICATION_MAX_DELAY_MS", 500.0),
            patch.object(main.random, "uniform", return_value=275.0),
        ):
            delay, source = main.select_notification_delay()

        self.assertEqual(delay, 0.275)
        self.assertEqual(source, "random")

    async def test_normal_notification_is_sent(self):
        with (
            patch.object(main, "NOTIFICATION_DELAY_SECONDS", 0.0),
            patch.object(main, "NOTIFICATION_MIN_DELAY_MS", 0.0),
            patch.object(main, "NOTIFICATION_MAX_DELAY_MS", 0.0),
            patch.object(main, "NOTIFICATION_FAILURE_MODE", "none"),
            patch.object(main, "NOTIFICATION_FAILURE_RATE", 0.0),
        ):
            result = await main.send_notification(self.make_request())

        self.assertEqual(result["status"], "SENT")
        self.assertIn("notification_id", result)

    async def test_forced_drop_returns_503(self):
        with (
            patch.object(main, "NOTIFICATION_DELAY_SECONDS", 0.0),
            patch.object(main, "NOTIFICATION_MIN_DELAY_MS", 0.0),
            patch.object(main, "NOTIFICATION_MAX_DELAY_MS", 0.0),
            patch.object(main, "NOTIFICATION_FAILURE_MODE", "drop"),
            patch.object(main, "NOTIFICATION_FAILURE_RATE", 0.0),
        ):
            result = await main.send_notification(self.make_request())

        self.assertEqual(result.status_code, 503)
        self.assertEqual(json.loads(result.body)["status"], "DROPPED")

    async def test_random_failure_rate_can_drop(self):
        with (
            patch.object(main, "NOTIFICATION_DELAY_SECONDS", 0.0),
            patch.object(main, "NOTIFICATION_MIN_DELAY_MS", 0.0),
            patch.object(main, "NOTIFICATION_MAX_DELAY_MS", 0.0),
            patch.object(main, "NOTIFICATION_FAILURE_MODE", "none"),
            patch.object(main, "NOTIFICATION_FAILURE_RATE", 0.05),
            patch.object(main.random, "random", return_value=0.01),
        ):
            result = await main.send_notification(self.make_request())

        self.assertEqual(result.status_code, 503)
        self.assertEqual(json.loads(result.body)["status"], "DROPPED")

    async def test_configured_delay_is_asynchronous(self):
        with (
            patch.object(main, "NOTIFICATION_DELAY_SECONDS", 10.0),
            patch.object(main, "NOTIFICATION_FAILURE_MODE", "none"),
            patch.object(main, "NOTIFICATION_FAILURE_RATE", 0.0),
            patch.object(main.asyncio, "sleep", new=AsyncMock()) as sleep_mock,
        ):
            result = await main.send_notification(self.make_request())

        sleep_mock.assert_awaited_once_with(10.0)
        self.assertEqual(result["status"], "SENT")


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from app.ha_client import DemoHomeAssistantClient, EntityState, read_token, state_to_float


class HomeAssistantClientHelperTests(unittest.TestCase):
    def test_state_to_float_accepts_numeric_strings(self) -> None:
        state = EntityState("sensor.test", "123.4", {})

        self.assertEqual(state_to_float(state), 123.4)

    def test_state_to_float_accepts_decimal_comma(self) -> None:
        state = EntityState("sensor.test", "12,5", {})

        self.assertEqual(state_to_float(state), 12.5)

    def test_state_to_float_rejects_unknown(self) -> None:
        state = EntityState("sensor.test", "unknown", {})

        self.assertIsNone(state_to_float(state))

    def test_demo_service_call_is_recorded(self) -> None:
        client = DemoHomeAssistantClient({"switch.pool": EntityState("switch.pool", "off", {})})

        result = client.call_service("switch", "turn_on", "switch.pool", dry_run=True)

        self.assertTrue(result["dry_run"])
        self.assertEqual(client.service_calls[0]["service"], "turn_on")

    def test_read_token_uses_environment(self) -> None:
        with patch.dict("os.environ", {"SUPERVISOR_TOKEN": "abc"}, clear=True):
            self.assertEqual(read_token("SUPERVISOR_TOKEN"), "abc")

    def test_read_token_uses_legacy_hassio_token(self) -> None:
        with patch.dict("os.environ", {"HASSIO_TOKEN": "legacy"}, clear=True):
            self.assertEqual(read_token("SUPERVISOR_TOKEN"), "legacy")

    def test_read_token_returns_none_when_missing(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(read_token("MISSING_TOKEN"))


if __name__ == "__main__":
    unittest.main()

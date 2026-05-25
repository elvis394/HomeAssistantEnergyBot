import unittest

from app.ha_client import DemoHomeAssistantClient, EntityState, state_to_float


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


if __name__ == "__main__":
    unittest.main()

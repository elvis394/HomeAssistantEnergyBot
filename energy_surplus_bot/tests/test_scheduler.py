import unittest
from datetime import datetime, timedelta

from app.config_store import validate_config_dict
from app.ha_client import DemoHomeAssistantClient, EntityState
from app.runtime_tracker import RuntimeEntry, RuntimeState
from app.scheduler import run_once
from tests.test_config_store import valid_config


class SchedulerTests(unittest.TestCase):
    def test_auto_mode_disabled_skips_turn_on_service_call(self) -> None:
        config = validate_config_dict(valid_config())
        client = DemoHomeAssistantClient.from_config(config)
        runtime = RuntimeState.empty_for_devices(config.enabled_devices, datetime(2026, 5, 25).date())

        result = run_once(config, client, runtime, now=datetime(2026, 5, 25, 9, 5))

        self.assertEqual(result.decisions[0].action, "turn_on")
        self.assertTrue(result.service_calls[0].skipped)
        self.assertIn("auto_mode", result.service_calls[0].reason)

    def test_auto_mode_dry_run_records_service_call(self) -> None:
        data = valid_config()
        data["app"]["auto_mode"] = True
        config = validate_config_dict(data)
        client = DemoHomeAssistantClient.from_config(config)
        runtime = RuntimeState.empty_for_devices(config.enabled_devices, datetime(2026, 5, 25).date())

        result = run_once(config, client, runtime, now=datetime(2026, 5, 25, 9, 5))

        self.assertFalse(result.service_calls[0].skipped)
        self.assertTrue(result.service_calls[0].response["dry_run"])
        self.assertEqual(client.service_calls[0]["service"], "turn_on")

    def test_runtime_sync_adds_finished_session_minutes(self) -> None:
        config = validate_config_dict(valid_config())
        client = DemoHomeAssistantClient.from_config(config)
        client.states["switch.pool_pump"] = EntityState("switch.pool_pump", "off", {})
        runtime = RuntimeState(
            {
                "pool_pump": RuntimeEntry(
                    device_name="pool_pump",
                    day="2026-05-25",
                    runtime_today_minutes=15,
                    last_started_at=datetime(2026, 5, 25, 10, 0),
                )
            }
        )

        run_once(config, client, runtime, now=datetime(2026, 5, 25, 10, 45))

        self.assertEqual(runtime.entries["pool_pump"].runtime_today_minutes, 60)
        self.assertIsNone(runtime.entries["pool_pump"].last_started_at)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.config_store import validate_config_dict
from app.runtime_tracker import (
    RuntimeEntry,
    RuntimeState,
    is_within_window,
    load_runtime_state,
    minutes_until_window_end,
    save_runtime_state,
)
from tests.test_config_store import valid_config


class RuntimeTrackerTests(unittest.TestCase):
    def test_time_window_matches_same_day_window(self) -> None:
        config = validate_config_dict(valid_config())
        window = config.devices[0].preferred_window

        self.assertTrue(is_within_window(window, datetime(2026, 5, 25, 12, 0)))
        self.assertFalse(is_within_window(window, datetime(2026, 5, 25, 20, 0)))

    def test_minutes_until_window_end(self) -> None:
        config = validate_config_dict(valid_config())
        window = config.devices[0].preferred_window

        self.assertEqual(minutes_until_window_end(window, datetime(2026, 5, 25, 17, 30)), 30)

    def test_runtime_with_current_session(self) -> None:
        entry = RuntimeEntry(
            device_name="pool_pump",
            day="2026-05-25",
            runtime_today_minutes=60,
            last_started_at=datetime(2026, 5, 25, 10, 0),
        )

        self.assertEqual(entry.runtime_with_current_session(True, datetime(2026, 5, 25, 10, 45)), 105)

    def test_min_off_guard(self) -> None:
        config = validate_config_dict(valid_config())
        device = config.devices[0]
        entry = RuntimeEntry(
            device_name=device.name,
            day="2026-05-25",
            last_stopped_at=datetime(2026, 5, 25, 10, 0),
        )

        self.assertFalse(entry.has_met_min_off(device, datetime(2026, 5, 25, 10, 10)))
        self.assertTrue(entry.has_met_min_off(device, datetime(2026, 5, 25, 10, 25)))

    def test_runtime_state_persistence(self) -> None:
        state = RuntimeState(
            {
                "pool_pump": RuntimeEntry(
                    device_name="pool_pump",
                    day="2026-05-25",
                    runtime_today_minutes=42,
                    last_started_at=datetime(2026, 5, 25, 10, 0),
                )
            }
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "runtime.json"
            save_runtime_state(path, state)

            loaded = load_runtime_state(path)

        self.assertEqual(loaded.entries["pool_pump"].runtime_today_minutes, 42)


if __name__ == "__main__":
    unittest.main()

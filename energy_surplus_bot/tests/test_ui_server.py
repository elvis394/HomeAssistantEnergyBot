import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.config_store import validate_config_dict
from app.ha_client import DemoHomeAssistantClient
from app.runtime_tracker import RuntimeState
from app.ui.server import (
    APP_JS,
    INDEX_HTML,
    build_history_payload,
    build_status_payload,
    config_to_dict,
    list_entity_payload,
)
from tests.test_config_store import valid_config


class UiServerHelperTests(unittest.TestCase):
    def test_config_to_dict_round_trips_for_validation(self) -> None:
        config = validate_config_dict(valid_config())

        data = config_to_dict(config)
        loaded = validate_config_dict(data)

        self.assertEqual(loaded.sources.grid_import_power_entity, config.sources.grid_import_power_entity)

    def test_entity_payload_lists_demo_entities(self) -> None:
        config = validate_config_dict(valid_config())
        client = DemoHomeAssistantClient.from_config(config)

        payload = list_entity_payload(client)

        self.assertTrue(any(item["entity_id"] == "switch.pool_pump" for item in payload))

    def test_status_payload_contains_snapshot_and_decisions(self) -> None:
        config = validate_config_dict(valid_config())
        client = DemoHomeAssistantClient.from_config(config)
        runtime = RuntimeState.empty_for_devices(config.enabled_devices, datetime(2026, 5, 25).date())

        payload = build_status_payload(config, client, runtime, now=datetime(2026, 5, 25, 9, 5))

        self.assertIn("snapshot", payload)
        self.assertIn("decisions", payload)
        self.assertIn("house_power_w", payload["snapshot"])
        self.assertEqual(payload["decisions"][0]["device_name"], "pool_pump")

    def test_status_payload_can_write_history(self) -> None:
        config = validate_config_dict(valid_config())
        client = DemoHomeAssistantClient.from_config(config)
        runtime = RuntimeState.empty_for_devices(config.enabled_devices, datetime(2026, 5, 25).date())
        with tempfile.TemporaryDirectory() as tmp_dir:
            history_path = Path(tmp_dir) / "history.json"

            build_status_payload(
                config,
                client,
                runtime,
                now=datetime(2026, 5, 25, 9, 5),
                history_path=history_path,
            )
            payload = build_history_payload(history_path)

        self.assertEqual(len(payload["entries"]), 1)
        self.assertEqual(payload["entries"][0]["house_power_w"], 680)

    def test_addon_brand_images_exist(self) -> None:
        root = Path(__file__).resolve().parents[1]

        self.assertTrue((root / "icon.png").exists())
        self.assertTrue((root / "logo.png").exists())

    def test_ui_uses_relative_paths_for_ingress(self) -> None:
        self.assertIn('href="app.css"', INDEX_HTML)
        self.assertIn('src="app.js"', INDEX_HTML)
        self.assertIn('src="icon.png"', INDEX_HTML)
        self.assertIn("getJson('api/status')", APP_JS)
        self.assertIn("getJson('api/history')", APP_JS)
        self.assertIn("fetch('api/config'", APP_JS)
        self.assertNotIn('href="/app.css"', INDEX_HTML)
        self.assertNotIn("getJson('/api/status')", APP_JS)


if __name__ == "__main__":
    unittest.main()

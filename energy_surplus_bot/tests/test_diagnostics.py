import unittest

from app.config_store import validate_config_dict
from app.diagnostics import build_energy_snapshot
from app.ha_client import DemoHomeAssistantClient, EntityState
from tests.test_config_store import valid_config


class DiagnosticsTests(unittest.TestCase):
    def test_demo_snapshot_aggregates_values(self) -> None:
        config = validate_config_dict(valid_config())
        client = DemoHomeAssistantClient.from_config(config)

        snapshot = build_energy_snapshot(config, client)

        self.assertEqual(snapshot.grid_export_w, 420)
        self.assertEqual(snapshot.grid_import_w, 0)
        self.assertEqual(snapshot.available_surplus_w, 270)
        self.assertGreater(snapshot.solar_input_w, snapshot.solar_output_w)
        self.assertTrue(snapshot.battery_near_target)
        self.assertGreater(snapshot.solar_surplus_risk_w, 0)

    def test_soc_average_strategy(self) -> None:
        data = valid_config()
        data["battery"]["soc_aggregation"] = "average"
        config = validate_config_dict(data)
        client = DemoHomeAssistantClient(
            {
                config.sources.grid_import_power_entity: EntityState(config.sources.grid_import_power_entity, "0", {}),
                config.sources.grid_export_power_entity: EntityState(config.sources.grid_export_power_entity, "0", {}),
                config.sources.anker_systems[0].solar_input_power_entity: EntityState(
                    config.sources.anker_systems[0].solar_input_power_entity, "0", {}
                ),
                config.sources.anker_systems[0].solar_output_power_entity: EntityState(
                    config.sources.anker_systems[0].solar_output_power_entity, "0", {}
                ),
                config.sources.anker_systems[0].battery_power_entity: EntityState(
                    config.sources.anker_systems[0].battery_power_entity, "0", {}
                ),
                config.sources.anker_systems[0].battery_soc_entity: EntityState(
                    config.sources.anker_systems[0].battery_soc_entity, "70", {}
                ),
                config.sources.anker_systems[1].solar_input_power_entity: EntityState(
                    config.sources.anker_systems[1].solar_input_power_entity, "0", {}
                ),
                config.sources.anker_systems[1].solar_output_power_entity: EntityState(
                    config.sources.anker_systems[1].solar_output_power_entity, "0", {}
                ),
                config.sources.anker_systems[1].battery_power_entity: EntityState(
                    config.sources.anker_systems[1].battery_power_entity, "0", {}
                ),
                config.sources.anker_systems[1].battery_soc_entity: EntityState(
                    config.sources.anker_systems[1].battery_soc_entity, "90", {}
                ),
            }
        )

        snapshot = build_energy_snapshot(config, client)

        self.assertEqual(snapshot.battery_soc_percent, 80)

    def test_non_numeric_sensor_creates_warning(self) -> None:
        config = validate_config_dict(valid_config())
        client = DemoHomeAssistantClient.from_config(config)
        client.states[config.sources.grid_export_power_entity] = EntityState(
            config.sources.grid_export_power_entity, "unknown", {}
        )

        snapshot = build_energy_snapshot(config, client)

        self.assertEqual(snapshot.grid_export_w, 0)
        self.assertTrue(any(config.sources.grid_export_power_entity in warning for warning in snapshot.warnings))


if __name__ == "__main__":
    unittest.main()

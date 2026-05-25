# Energy Surplus Bot

This add-on watches Home Assistant energy data and decides when flexible loads should run from solar surplus.

## Safe Defaults

The add-on starts defensively:

- `auto_mode: false`
- `dry_run: true`

With these defaults, the bot observes and explains decisions but does not switch devices.

## Configuration

Configure the add-on options in Home Assistant or through the built-in web UI.

Important entities:

- grid import power sensor
- grid export power sensor
- house power sensor, optional but recommended
- Anker Solix PV input power sensor per system
- Anker Solix output power sensor per system
- Anker Solix battery SOC sensor per system
- Anker Solix battery power sensor per system
- switch entities for flexible loads

## Enabling Real Switching

Real service calls only happen when both settings are changed deliberately:

- `auto_mode: true`
- `dry_run: false`

Keep `dry_run: true` until the shown decisions match your expectations.

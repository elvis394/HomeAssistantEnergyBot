# Energy Surplus Bot

Home Assistant add-on that watches solar production, grid import/export, Anker Solix battery state and flexible loads. It starts in a defensive mode and explains every decision before real switching is enabled.

## Current MVP

- Reads two Anker Solix systems.
- Supports separate grid import and grid export sensors.
- Aggregates PV input, solar output, battery SOC and battery power.
- Shows total house consumption from a configured sensor or derived fallback.
- Tracks daily runtime per device.
- Stores a compact local history of recent measurements and decisions.
- Decides whether configured switches should turn on, turn off or stay unchanged.
- Includes a built-in web UI on port `8099`.
- Runs a background scheduler while the web UI is active.
- Defaults to `auto_mode: false` and `dry_run: true`.

## Safe Startup

Real service calls only happen when both conditions are changed deliberately:

- `auto_mode: true`
- `dry_run: false`

Keep `dry_run: true` until the decisions shown in the UI match your expectations.

## Local Development

Run one demo tick:

```powershell
C:\Users\michi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m app.main --once
```

Start the local UI with demo states:

```powershell
C:\Users\michi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m app.main --serve
```

Run tests:

```powershell
C:\Users\michi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -v
```

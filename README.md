# Home Assistant Energy Bot Add-ons

GitHub add-on repository for the Energy Surplus Bot.

## Installation In Home Assistant

1. Push this repository to GitHub.
2. Replace the placeholder URL in [repository.yaml](repository.yaml) with your real GitHub repository URL.
3. In Home Assistant open **Settings -> Add-ons -> Add-on Store**.
4. Open the three-dot menu and choose **Repositories**.
5. Add your GitHub repository URL.
6. Install **Energy Surplus Bot** from the new repository entry.

The add-on itself lives in [energy_surplus_bot](energy_surplus_bot/).

## Local Development

From the add-on folder:

```powershell
cd energy_surplus_bot
C:\Users\michi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -v
```

Run one demo tick:

```powershell
cd energy_surplus_bot
C:\Users\michi\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m app.main --once
```

#  DND Flow - Documentation

This documentation folder covers the full project: Discord bot runtime, online web dashboard, offline backup dashboard, command registration, and file-by-file reference.

## License and intended use

DND Flow is distributed for personal, private, educational, and other non-commercial self-hosted use.
Commercial use, paid hosting, resale, or monetized redistribution require prior written permission from the project maintainer(s).
See the root `LICENSE` file for the full terms.

## Documentation Map

- `docs/README.md` (this file): architecture, startup, and operational workflows
- `docs/COMMAND_REGISTRATION.md`: slash command sync behavior and troubleshooting
- `docs/FILE_REFERENCE.md`: full file catalog with purpose and usage notes

## Project Components

1. `Discord_Bot/`
- Primary Discord bot process (`main.py`)
- Loads command cogs from `Discord_Bot/commands/`
- Reads/writes SQLite databases in `Discord_Bot/databases/`

2. `Online_Web_Server/`
- OAuth-protected web dashboard for remote/admin use
- Intended for internet-facing use behind HTTPS (typically via Caddy)
- Single launcher script: `Online_Web_Server/start.bat`

3. `Offline_Backup_Web_Server/`
- Local backup/admin dashboard workflow
- Intended for local use (non-public/offline operations)
- Single launcher script: `Offline_Backup_Web_Server/start.bat`

## Quick Start (Recommended Order)

1. Install Python 3.11+.
2. From the root `DND Flow/`, run `setup_install.bat` to create `.venv`, install dependencies, and generate local `.env` files from the examples.
3. Open the generated `.env` files and fill in your own local values:
- `Discord_Bot/.env`
- `Online_Web_Server/.env` (if using the online dashboard)
- `Offline_Backup_Web_Server/.env` (if using the offline dashboard)
4. Start services as needed:
- Bot: `Discord_Bot/start_bot.bat` or `python Discord_Bot/main.py`
- Online dashboard: `Online_Web_Server/start.bat`
- Offline dashboard: `Offline_Backup_Web_Server/start.bat`

### Export-safe package contents

Shared/exported copies should only contain source code, templates, and documentation.

- Live `.env` files are intentionally excluded
- SQLite databases, logs, uploads, cached server icons, and Python cache folders should stay empty or untracked
- Run `setup_install.bat` after extracting the package to rebuild the environment on the target machine

## Runtime Modes

1. Bot only
- Run only `Discord_Bot/main.py`.
- Use slash commands directly in Discord.

2. Bot + Online dashboard
- Run bot plus `Online_Web_Server/start.bat`.
- Use Discord OAuth login and your public base URL.

3. Bot + Offline dashboard
- Run bot plus `Offline_Backup_Web_Server/start.bat`.
- Use local backup workflow (not intended for internet exposure).

## Script Behavior

1. `Online_Web_Server/start.bat`
- Single-terminal launcher
- Starts Caddy in background and Flask in foreground
- `Ctrl + C` stops Flask; prompt allows restart or quit

2. `Offline_Backup_Web_Server/start.bat`
- Single-terminal launcher
- Starts Flask in foreground for localhost backup/admin workflow
- `Ctrl + C` stops Flask; prompt allows restart or quit

## Database Ownership

All dashboards read/write the bot databases in `Discord_Bot/databases/`.

- `Settings.db`: server config, roles, channels, dashboard settings
- `Sheets.db`: sheet records and field/template data
- `Shop.db`: item catalog and shop settings
- `Economy.db`: currency/jobs/work data
- `Inventory.db`: user inventory data
- `Combat.db`: combat/death settings and state
- `Audit.db`: dashboard and change auditing

Restart the bot after major dashboard-side configuration updates.

## Testing

From `Discord_Bot/`:

```bash
python -m pytest test_bot.py -v
```

## Operations Notes

1. Secrets
- Keep real tokens/secrets only in local `.env` files.

2. Runtime artifacts
- Logs, SQLite data, and uploaded/static runtime assets should not be treated as source files.

3. Startup script policy
- Active launchers are `Online_Web_Server/start.bat` and `Offline_Backup_Web_Server/start.bat`.

For complete per-file documentation, see `docs/FILE_REFERENCE.md`.

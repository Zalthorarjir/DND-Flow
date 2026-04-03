# Full File Reference

This file catalogs project files and explains what each file is for and when to use it.

## Scope

Included components:
- `Discord_Bot/`
- `docs/`
- `Online_Web_Server/`
- `Offline_Backup_Web_Server/`

Local-only or export-sanitized runtime content:
- `.env` files created from `.env.example`
- SQLite databases under `Discord_Bot/databases/`
- Logs, uploads, cached server icons, and other user-generated assets

Excluded from detailed source documentation:
- Virtual environments (`.venv/`, `venv/`)
- Python cache folders (`__pycache__/`)
- Bundled third-party binaries under `tools/caddy/` are treated as vendor content

## Project root

- `setup_install.bat`
  - Root Windows bootstrap script.
  - Creates `.venv`, installs all Python dependencies, and copies local `.env` files from the safe examples when missing.

- `.gitignore`
  - Root export-safety ignore rules for secrets, caches, logs, databases, and generated assets.

## Discord_Bot

### Core runtime

- `Discord_Bot/main.py`
  - Bot entrypoint.
  - Loads cogs, initializes DB dependencies, starts Discord connection.
  - Use when starting the Discord bot process.

- `Discord_Bot/requirements.txt`
  - Python dependencies for bot runtime and tests.
  - Install with `pip install -r requirements.txt` in `Discord_Bot/`.

- `Discord_Bot/start_bot.bat`
  - Windows helper to run the bot.
  - Use on Windows instead of manually typing Python command.

- `Discord_Bot/test_bot.py`
  - Consolidated automated tests.
  - Run with `python -m pytest test_bot.py -v`.

### Configuration files

- `Discord_Bot/.env`
  - Local-only runtime secrets and bot configuration generated from `.env.example`.
  - Keep this file private and exclude it from exported/shareable packages.

- `Discord_Bot/.env.example`
  - Safe template for required env variables.
  - Copy to `.env` and fill values.

- `Discord_Bot/.gitignore`
  - Ignore rules specific to bot folder.

### Tooling and cache artifacts

- `Discord_Bot/.pytest_cache/.gitignore`
- `Discord_Bot/.pytest_cache/CACHEDIR.TAG`
- `Discord_Bot/.pytest_cache/README.md`
- `Discord_Bot/.pytest_cache/v/cache/lastfailed`
- `Discord_Bot/.pytest_cache/v/cache/nodeids`

These are pytest-managed cache files for local test execution state.

### Command modules (`Discord_Bot/commands`)

- `Discord_Bot/commands/__init__.py`
  - Package marker for command modules.

- `Discord_Bot/commands/Config.py`
  - Slash commands for server config/admin settings.

- `Discord_Bot/commands/Sheets.py`
  - Sheet creation/search/review lifecycle commands.

- `Discord_Bot/commands/sheet_storage.py`
  - Shared storage helpers for sheet persistence.

- `Discord_Bot/commands/Economy.py`
  - Currency/jobs/work and related economy operations.

- `Discord_Bot/commands/Inventory.py`
  - Inventory operations and item ownership updates.

- `Discord_Bot/commands/Market.py`
  - Item catalog and shop buy/sell flows.

- `Discord_Bot/commands/Combat.py`
  - Combat mechanics, health, death/revive workflows.

- `Discord_Bot/commands/audit_log.py`
  - Audit log utilities for tracked actions.

- `Discord_Bot/commands/Help.py`
  - Help command/group for command discovery.

### Databases (`Discord_Bot/databases`)

- `Discord_Bot/databases/Settings.db`
  - Guild configuration, role/channel mappings, and app settings.

- `Discord_Bot/databases/Sheets.db`
  - Character sheets, templates, and field definitions.

- `Discord_Bot/databases/Shop.db`
  - Shop and item catalog records.

- `Discord_Bot/databases/Economy.db`
  - Currency balances, work/job records.

- `Discord_Bot/databases/Inventory.db`
  - User inventory entries and item quantities.

- `Discord_Bot/databases/Combat.db`
  - Combat/death configuration and status data.

- `Discord_Bot/databases/Audit.db`
  - Auditable action history.

## docs

- `docs/README.md`
  - Project docs index, architecture overview, startup usage.

- `docs/COMMAND_REGISTRATION.md`
  - Slash command sync internals and troubleshooting.

- `docs/FILE_REFERENCE.md`
  - This full file reference.

## Online_Web_Server

### Core runtime

- `Online_Web_Server/app.py`
  - Flask application for OAuth-protected online dashboard.

- `Online_Web_Server/requirements.txt`
  - Python dependencies for online dashboard.

- `Online_Web_Server/start.bat`
  - Single launcher for online server stack.
  - Starts Caddy + Flask in one terminal with restart prompt.

### Config and docs

- `Online_Web_Server/.env`
  - Local-only runtime configuration and OAuth secrets generated from `.env.example`.

- `Online_Web_Server/.env.example`
  - Template env file for setup.

- `Online_Web_Server/.gitignore`
  - Ignore rules for online server artifacts.

- `Online_Web_Server/README.md`
  - Service-specific setup and behavior notes.

- `Online_Web_Server/QUICKSTART.txt`
  - Fast-start operational steps.

### Reverse proxy config

- `Online_Web_Server/Caddyfile`
  - Active Caddy config for online proxy/TLS.

- `Online_Web_Server/Caddyfile.example`
  - Starter Caddy config template.

### Bundled third-party tool docs

- `Online_Web_Server/tools/caddy/LICENSE`
- `Online_Web_Server/tools/caddy/README.md`

These describe the bundled Caddy distribution/license details.

### Frontend assets

- `Online_Web_Server/static/style.css`
  - Dashboard styling.

- `Online_Web_Server/static/script.js`
  - Dashboard client-side logic.

- `Online_Web_Server/static/icon.png`
  - App icon asset.

- `Online_Web_Server/static/server_icons/`
  - Runtime-cached server icon assets.
  - Keep this folder empty in exported/shareable packages.

- `Online_Web_Server/templates/base.html`
  - Shared template shell/layout.

- `Online_Web_Server/templates/dashboard.html`
  - Main dashboard view.

- `Online_Web_Server/templates/admin_dashboard.html`
  - Admin-focused dashboard panels.

- `Online_Web_Server/templates/account.html`
  - Account/user page.

- `Online_Web_Server/templates/login.html`
  - OAuth login page.

- `Online_Web_Server/templates/server_selector.html`
  - Active server/guild selection UI.

- `Online_Web_Server/templates/no_role_access.html`
  - Access denied page for missing role permissions.

- `Online_Web_Server/templates/items.html`
  - Items management/shop item view.

- `Online_Web_Server/templates/shop.html`
  - Shop management/interaction page.

- `Online_Web_Server/templates/jobs.html`
  - Jobs and work-related dashboard page.

- `Online_Web_Server/templates/cooldown.html`
  - Cooldown/workflow status page.

- `Online_Web_Server/templates/_dashboard_check.js`
  - Dashboard-side JS helper loaded by templates.

### Runtime logs and uploads

- `Online_Web_Server/logs/caddy.log`
- `Online_Web_Server/logs/caddy.error.log`
- `Online_Web_Server/logs/online_web_server.log`
- `Online_Web_Server/logs/online_web_server.error.log`

These are runtime logs (Flask/Caddy) and operational artifacts, not source code.

- `Online_Web_Server/uploads/items/`
  - Uploaded item images/files.

## Offline_Backup_Web_Server

### Core runtime

- `Offline_Backup_Web_Server/app.py`
  - Flask application for offline/local backup workflow.

- `Offline_Backup_Web_Server/requirements.txt`
  - Python dependencies for offline dashboard.

- `Offline_Backup_Web_Server/start.bat`
  - Single launcher for offline server.
  - Runs Flask in one terminal with restart prompt.

### Config and docs

- `Offline_Backup_Web_Server/.env`
  - Runtime configuration for offline server.

- `Offline_Backup_Web_Server/.env.example`
  - Template env file for offline setup.

- `Offline_Backup_Web_Server/.gitignore`
  - Ignore rules for offline artifacts.

- `Offline_Backup_Web_Server/README.md`
  - Service-specific setup notes.

- `Offline_Backup_Web_Server/QUICKSTART.txt`
  - Fast-start operational steps.

### Startup scripts

- `Offline_Backup_Web_Server/start.bat`

This is the active offline launcher script.

### Reverse proxy config (optional/offline context)

- `Offline_Backup_Web_Server/Caddyfile`
- `Offline_Backup_Web_Server/Caddyfile.example`

### Bundled third-party tool docs

- `Offline_Backup_Web_Server/tools/caddy/LICENSE`
- `Offline_Backup_Web_Server/tools/caddy/README.md`

### Frontend assets

- `Offline_Backup_Web_Server/static/style.css`
- `Offline_Backup_Web_Server/static/script.js`
- `Offline_Backup_Web_Server/static/icon.png`
- `Offline_Backup_Web_Server/static/server_icons/1168989553722400780_2c01fdaf211e59b8f2ac20dd9b921411.png`
- `Offline_Backup_Web_Server/static/server_icons/1296259358187061249_5f36bae8d4ab63b4ac3e4a011d788c78.png`
- `Offline_Backup_Web_Server/templates/base.html`
- `Offline_Backup_Web_Server/templates/dashboard.html`
- `Offline_Backup_Web_Server/templates/admin_dashboard.html`
- `Offline_Backup_Web_Server/templates/account.html`
- `Offline_Backup_Web_Server/templates/login.html`
- `Offline_Backup_Web_Server/templates/server_selector.html`
- `Offline_Backup_Web_Server/templates/items.html`
- `Offline_Backup_Web_Server/templates/shop.html`
- `Offline_Backup_Web_Server/templates/jobs.html`
- `Offline_Backup_Web_Server/templates/cooldown.html`
- `Offline_Backup_Web_Server/templates/_dashboard_check.js`

### Runtime logs and uploads

- `Offline_Backup_Web_Server/logs/caddy.log`
- `Offline_Backup_Web_Server/logs/offline_web_server.log`
- `Offline_Backup_Web_Server/logs/online_web_server.log`

These are runtime logs and operational artifacts.

- `Offline_Backup_Web_Server/uploads/items/`
  - Uploaded item files/images.

## Usage Summary

1. For Discord slash commands and game workflows, run `Discord_Bot/main.py`.
2. For internet-facing admin dashboard, run `Online_Web_Server/start.bat`.
3. For local backup/admin workflow, run `Offline_Backup_Web_Server/start.bat`.
4. For command visibility issues, follow `docs/COMMAND_REGISTRATION.md`.

# DND Flow - Online Web Server

`Online_Web_Server` is the OAuth-protected web dashboard for managing the bot data in `Discord_Bot/databases`.

## Quick Start

1. Open `Online_Web_Server/.env` and set OAuth values.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the web server:

```bash
python app.py
```

4. Open your configured `PUBLIC_BASE_URL` and sign in with Discord.

## OAuth Configuration

Use these keys in `Online_Web_Server/.env`:

```env
DISCORD_CLIENT_ID=your_discord_application_client_id
DISCORD_CLIENT_SECRET=your_discord_application_client_secret
DISCORD_REDIRECT_URI=https://your-domain-or-ip:5000/callback
DISCORD_OAUTH_SCOPE=identify

ONLINE_WEB_SERVER_HOST=127.0.0.1
ONLINE_WEB_SERVER_PORT=5000
PUBLIC_BASE_URL=https://your-domain-or-ip:5000

ONLINE_WEB_SERVER_SSL_CERT=
ONLINE_WEB_SERVER_SSL_KEY=
TRUST_PROXY_HEADERS=True

FLASK_SECRET_KEY=your-random-secret
FLASK_ENV=production
FLASK_DEBUG=False
```

Discord developer portal redirect URI must exactly match `DISCORD_REDIRECT_URI`.

## Bot Integration

The dashboard reads and writes bot data directly from:

- `Discord_Bot/databases/Settings.db`
- `Discord_Bot/databases/Sheets.db`
- `Discord_Bot/databases/Shop.db`
- `Discord_Bot/databases/Economy.db`
- `Discord_Bot/databases/Inventory.db`
- `Discord_Bot/databases/Combat.db`
- `Discord_Bot/databases/Audit.db`

Restart the Discord bot after major settings changes so runtime command behavior reflects updates.

## Reverse Proxy (Caddy)

If hosting publicly, terminate TLS with Caddy and reverse proxy to Flask.

1. Install Caddy separately from the official releases and either put `caddy.exe` in `tools/caddy/` locally or make `caddy` available in your system `PATH`.
2. Copy `Caddyfile.example` to `Caddyfile` and set your hostname.
3. Start the web server with `start.bat` so Flask runs in the foreground and Caddy is managed from the same launcher when available.
4. Use `Ctrl + C` to stop the stack, then press Enter in the same terminal to restart when prompted.

The Caddy binary is intentionally not bundled in the repository so GitHub uploads stay below file-size limits. Only placeholder domains should be kept in exported packages; set your real domain locally after deployment.

## Notes

- OAuth is required for all dashboard/API routes except login/callback/static.
- New naming is `ONLINE_WEB_SERVER_*` for host/port/SSL keys.
- Legacy `USER_SERVER_*` keys are still accepted by `app.py` as fallback.
├── Settings.db              # Server config, roles, channels
├── Sheets.db                # Character, sheet, field, and guild template data
├── Shop.db                  # Shop + item catalog tables
├── Economy.db               # Currency, jobs, and work claims
├── Inventory.db             # Inventory rows per user + character
├── Combat.db                # Combat rules + death settings
└── Audit.db                 # Dashboard and command audit logs
```

All databases are SQLite files. The dashboard creates tables automatically as needed.

## 📝 Support

For issues with the admin panel, check:
1. Make sure the bot databases exist in `Discord_Bot/databases/`
2. Ensure Python is installed and added to PATH
3. Check that port 5000 is not already in use
4. Make sure all dependencies are installed: `pip install -r requirements.txt`

## License

Part of the DND Flow project.

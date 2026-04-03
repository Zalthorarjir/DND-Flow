# DND Flow

DND Flow is a self-hosted Discord bot with optional online and offline web dashboards for local/home use.

## Quickstart (< 2 minutes)

**What:** A self-hosted Discord bot and web dashboard that manages DnD character sheets, inventory, economy, combat, and shops for your server.

**Who:** DnD players and DMs who want game-management tools inside Discord without relying on third-party services.

### Prerequisites

- [Python 3.11+](https://www.python.org/downloads/) installed
- A [Discord bot token](https://discord.com/developers/applications) (create an app → Bot → copy token)
- Windows (`.bat` scripts included)

### Steps

```bash
# 1. Clone the repo
git clone https://github.com/Zalthorarjir/DND-Flow.git
cd DND-Flow

# 2. Run the installer (creates venv, installs deps, generates .env files)
setup_install.bat

# 3. Add your bot token
#    Open Discord_Bot\.env and set:
#    DISCORD_TOKEN=your-token-here

# 4. Start the bot
Discord_Bot\start_bot.bat
```

### Try it — Example DnD Flow

Once the bot is online in your Discord server, run these slash commands:

| Step | Command | What happens |
|------|---------|--------------|
| 1 | `/new` | Create a new character sheet |
| 2 | `/edit` | Fill in your character's stats and details |
| 3 | `/submit` | Submit the sheet for DM approval |
| 4 | `/help` | See all available commands |

**Optional:** Start the offline web dashboard for a local admin panel:
```bash
Offline_Backup_Web_Server\start.bat
# Opens at http://localhost:5002 — no login required
```

---

## License

This project is distributed under the `DND Flow Non-Commercial Home Use License`.

### What this means
- ✅ Personal, private, educational, and hobby use are allowed
- ✅ Self-hosting at home is allowed
- ✅ Modifying the project for your own non-commercial use is allowed
- ❌ Selling the project is not allowed
- ❌ Paid hosting or offering it as a revenue-generating service is not allowed without written permission
- ❌ Commercial redistribution is not allowed without written permission

See the full terms in [`LICENSE`](LICENSE).

## Setup

1. Run `setup_install.bat`
2. Fill in your local `.env` values
3. Start the component(s) you want:
   - `Discord_Bot\start_bot.bat`
   - `Online_Web_Server\start.bat`
   - `Offline_Backup_Web_Server\start.bat`

If you want HTTPS / reverse-proxy support for the online dashboard, install Caddy separately from the official releases. The repository does not bundle the large `caddy.exe` binary so GitHub uploads stay within file-size limits.

## Support and contact

If you are the maintainer, host, or someone working on this project and need to reach out:

- GitHub: https://github.com/Zalthorarjir
- Discord: `@zalthorarjir`

Please avoid posting secrets, tokens, private server data, or personal user information in public issues.

## Notes

This repository is intended as a home/self-hosted project distribution. Keep your secrets, tokens, logs, and runtime databases private and out of version control.

Project assembled and maintained by its publisher, with development assistance from GitHub Copilot.

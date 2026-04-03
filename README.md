# DND Flow

DND Flow is a self-hosted Discord bot with optional online and offline web dashboards for local/home use.

## Quickstart (< 2 minutes)

**What:** A self-hosted Discord bot and web dashboard that manages DnD character sheets, inventory, economy, combat, and shops for your server.

**Who:** DnD players and DMs who want game-management tools inside Discord without relying on third-party services.

### Prerequisites

- [Python 3.11+](https://www.python.org/downloads/) installed
- Windows (`.bat` scripts included)
- A Discord application — set one up at the [Discord Developer Portal](https://discord.com/developers/applications):

#### Discord Developer Portal Setup

1. **Create a New Application** → go to the **Bot** tab → click **Reset Token** → copy and save your bot token.
   - ➡️ Paste the token into `Discord_Bot\.env` as `DISCORD_TOKEN=your-token-here`
2. **OAuth2 → General**
   - Copy your **Client ID** from the top of the page.
   - Click **Reset Secret** to generate a **Client Secret** — copy and save it.
   - Add a **Redirect URL**: `https://example.com/callback` (replace with your actual domain, e.g. `https://yourdomain.com/callback`)
   - ➡️ Paste these into `Online_Web_Server\.env`:
     ```
     DISCORD_CLIENT_ID=your-client-id-here
     DISCORD_CLIENT_SECRET=your-client-secret-here
     DISCORD_REDIRECT_URI=https://yourdomain.com/callback
     ```
     > The Redirect URL in the Developer Portal **must exactly match** `DISCORD_REDIRECT_URI` in your `.env` file.
3. **Installation → Installation Contexts**
   - Enable **Guild Install**
   - **Scopes:** `applications.commands`, `bot`
   - **Permissions:**

     | Permission | ✅ |
     |---|---|
     | Administrator | ✅ |
     | Manage Roles | ✅ |
     | Manage Webhooks | ✅ |
     | Manage Messages | ✅ |
     | Read Message History | ✅ |
     | Send Messages | ✅ |
     | Embed Links | ✅ |
     | Attach Files | ✅ |
     | Use Slash Commands | ✅ |
     | View Channels | ✅ |

### Steps

```bash
# 1. Clone the repo
git clone https://github.com/Zalthorarjir/DND-Flow.git
cd DND-Flow

# 2. Run the installer (creates venv, installs deps, generates .env files)
setup_install.bat

# 3. Fill in your .env files with the values from the Developer Portal (see above):
#    Discord_Bot\.env            → DISCORD_TOKEN
#    Online_Web_Server\.env      → DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI

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

## Commands

All commands use Discord slash commands (`/`). Arguments in `<>` are required, arguments in `()` are optional.

### Config

| Command | Description |
|---|---|
| `/config role <admin\|member> <role>` | Set the admin or member role |
| `/config channel <admin\|member> <channel>` | Set the admin or member channel |
| `/config field add <fieldname> (required)` | Add a field to the sheet template |
| `/config field remove <fieldname>` | Remove a field from the sheet template |
| `/config delete <user> <name>` | [Admin] Permanently delete a user's character and sheet |
| `/config reset <Sheets\|Roles\|Fields\|Channels>` | Reset sheets, roles, fields, or channels |
| `/config work_cooldown <days>` | Set the work cooldown time in days (0 = no cooldown) |

### Sheet

| Command | Description |
|---|---|
| `/sheet new <name>` | Create a new character sheet |
| `/sheet edit <sheetid> <field name>` | Edit a field on a character sheet |
| `/sheet submit` | Submit a character sheet for admin review |
| `/sheet remove <name>` | Permanently delete a character sheet |
| `/sheet list` | View all your character sheets and their statuses |
| `/sheet icon <sheetid>` | Set an icon image for a character sheet |
| `/sheet drafts` | View your sheets still in Draft status (with sheet IDs) |
| `/sheet pending` | [Admin] View all pending sheets awaiting review |
| `/search (name) (user)` | Search for approved character sheets by name or user |

### Inventory

| Command | Description |
|---|---|
| `/inventory add <mention> <item_name> <quantity> (name)` | [Admin] Add an item to a user's inventory or character |
| `/inventory view <mention> (name)` | View a user's inventory or character inventory |
| `/inventory remove <mention> <item_name> <quantity> (name)` | [Admin] Remove an item from a user's inventory or character |

### Item

| Command | Description |
|---|---|
| `/item add <name> <consumable> (image) (description)` | Add a new item definition |
| `/item remove <name>` | Remove an item by name |
| `/item list` | List all items |
| `/item set consumable <name> <Yes\|No>` | Set an item's consumable status |
| `/item set description <name>` | Set or update an item's description |
| `/item set image <name> <image>` | Set or update an item's image |

### Shop

| Command | Description |
|---|---|
| `/shop add <item> <price>` | Add an item to the shop |
| `/shop remove <item>` | Remove an item from the shop |
| `/shop view` | List all items available in the shop |
| `/shop buy <item> <quantity> (name)` | Buy an item from the shop |
| `/shop sell <item> <quantity> (name)` | Sell an item to the shop |

### Currency

| Command | Description |
|---|---|
| `/currency view <mention> (name)` | View a user's currency amount |
| `/currency set <mention> <amount> (name)` | Set a user's currency amount |
| `/currency remove <mention> <amount> (name)` | Remove an amount from a user's currency |

### Work / Economy

| Command | Description |
|---|---|
| `/work create <job> <payment>` | Create a new job with a payment amount |
| `/work edit <job> <payment>` | Edit an existing job's payment amount |
| `/work assign <job> <mention> <name>` | Assign a job to a user's character |
| `/job <name>` | Claim your job payout for a character |
| `/give_money <name> <amount> <mention> <recipient_name>` | Give currency to another user or character |
| `/give_item <name> <item> <count> <mention> <recipient_name>` | Give an item to another user or character |

### Combat

| Command | Description |
|---|---|
| `/fight-dynamic dynamic <oc> <opponent> <opponentoc>` | Start a dynamic fight between two characters |
| `/fight-dynamic rules <solid_hit> <small_hit> <missed> <self_hit>` | Set the attack outcome chances |
| `/health_track <name> <hp>` | Track HP for a character |

### Death

| Command | Description |
|---|---|
| `/death claim <mention> <name>` | Claim a character's death for admin approval |
| `/death set <time>` | Set the global death cooldown in days |
| `/death infinite <Yes\|No>` | Set death to permanent or cooldown-based |
| `/death reset <mention> <name>` | Reset a character's death status |
| `/death check <name>` | Check your character's death cooldown status |
| `/death revive <name>` | Revive a dead character if the cooldown is over |
| `/death list` | List your characters currently reported as dead |
| `/death graveyard` | List all characters currently reported as dead |

### Help

| Command | Description |
|---|---|
| `/help` | Show help for all commands, grouped by category |

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
2. Fill in your local `.env` values (see [Discord Developer Portal Setup](#discord-developer-portal-setup) above):
   - `Discord_Bot\.env` → `DISCORD_TOKEN`
   - `Online_Web_Server\.env` → `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_REDIRECT_URI`
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

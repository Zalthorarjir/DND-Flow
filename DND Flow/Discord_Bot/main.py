#################################################################
#              Professional Discord Bot (discord.py)           #
#          Self-hosted service for game mechanics               #
#################################################################

"""
Main entry point for the Discord bot.
Handles initialization, extension loading, and bot startup.
"""

import os
import sqlite3
import discord
from discord.ext import commands
from dotenv import dotenv_values
import asyncio

from commands.audit_log import build_discord_interaction_details, write_discord_audit_log

BOT_ENV_PATH = os.path.join(os.path.dirname(__file__), '.env')


def get_discord_token():
    """Load the bot token only from Discord_Bot/.env."""
    values = dotenv_values(BOT_ENV_PATH)
    token = values.get('DISCORD_TOKEN')
    return str(token).strip() if token else None


intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix="/", intents=intents)


# Ensure Settings.db exists in databases/
db_directory = 'databases/'
db_path = os.path.join(db_directory, "Settings.db")
print(f"Checking database path: {db_path}")
if not os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    print(f'Created database file: Settings.db')
    conn.close()

# Ensure Sheets.db schema is up to date
from commands.sheet_storage import ensure_schema as _ensure_sheet_schema
_ensure_sheet_schema()
print("✓ Sheets.db schema ready")


def ensure_server_row(guild_id: int) -> bool:
    """Ensure a blank Server row exists for a guild; return True when inserted."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS Server (
        guild_id INTEGER PRIMARY KEY,
        admin_role_id INTEGER,
        admin_channel_id INTEGER,
        member_role_id INTEGER,
        member_channel_id INTEGER
    )''')
    c.execute('INSERT OR IGNORE INTO Server (guild_id) VALUES (?)', (int(guild_id),))
    inserted = c.rowcount > 0
    conn.commit()
    conn.close()
    return inserted


def ensure_server_rows_for_guilds(guilds: list[discord.Guild]) -> int:
    """Ensure Server rows for all guilds the bot is currently in."""
    inserted = 0
    for guild in guilds:
        if ensure_server_row(guild.id):
            inserted += 1
    return inserted

# --- Import-review button handler ---

from discord import ui

class _ImportReviewModal(ui.Modal):
    """Comment modal shown when an admin acts on an imported-backup sheet."""
    def __init__(self, action: str, storage_sheet_id: int, member_id: str, action_callback):
        super().__init__(title=f"{action} — Optional Comment")
        self._action = action
        self._sid    = storage_sheet_id
        self._mid    = member_id
        self._cb     = action_callback
        self.comment = ui.TextInput(
            label="Comment (optional)",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000,
        )
        self.add_item(self.comment)

    async def on_submit(self, interaction: discord.Interaction):
        await self._cb(interaction, self._action, self._sid, self._mid, self.comment.value or "")


async def _handle_import_review_button(interaction: discord.Interaction):
    """Resolve and dispatch import-review button clicks from admin channel."""
    custom_id = (interaction.data or {}).get('custom_id', '')
    # custom_id format: import_rev:<action>:<storage_sheet_id>:<user_id>
    parts = custom_id.split(':')
    if len(parts) != 4:
        await interaction.response.send_message("Malformed button ID.", ephemeral=True)
        return

    _, action_key, sid_str, member_id = parts
    action_map = {'approve': 'Approved', 'deny': 'Denied', 'discuss': 'Discuss'}
    action = action_map.get(action_key)
    if not action:
        await interaction.response.send_message("Unknown action.", ephemeral=True)
        return

    try:
        storage_sheet_id = int(sid_str)
    except ValueError:
        await interaction.response.send_message("Invalid sheet ID.", ephemeral=True)
        return

    from commands.sheet_storage import (
        promote_draft_to_approved, set_sheet_status,
        record_review, clear_pending_review, get_fields, get_channel_ids,
        connect_db,
    )
    from commands.Sheets import _build_embeds

    async def apply_action(inter: discord.Interaction, act: str, sid: int, mid: str, comment: str):
        try:
            # Resolve character name from Sheets.db before status changes.
            conn_sh = connect_db()
            try:
                row = conn_sh.execute(
                    '''SELECT c.name FROM characters c
                       JOIN sheets s ON s.character_id = c.character_id
                       WHERE s.sheet_id = ?''',
                    (sid,),
                ).fetchone()
                char_name = row['name'] if row else f'Sheet {sid}'
            finally:
                conn_sh.close()

            # Apply status change in Sheets.db.
            final_status = act  # what SheetIndex should record
            if act == 'Approved':
                promote_draft_to_approved(sid)
            elif act == 'Denied':
                set_sheet_status(sid, 'Draft')
                final_status = 'Draft'
            else:
                set_sheet_status(sid, act)

            record_review(sid, str(inter.user.id), act, comment)
            clear_pending_review(sid)

            # Sync SheetIndex in Settings.db so the web server reflects the change.
            try:
                import time as _time
                conn_idx = sqlite3.connect(db_path)
                conn_idx.execute(
                    'UPDATE SheetIndex SET status=?, updated_at=? WHERE storage_sheet_id=?',
                    (final_status, int(_time.time()), sid),
                )
                conn_idx.commit()
                conn_idx.close()
            except Exception:
                pass

            # Disable buttons on the admin message.
            try:
                if inter.message:
                    await inter.message.edit(view=None)
            except Exception:
                pass

            # Notify the member channel.
            fields = get_fields(sid)
            reviewer_name = getattr(inter.user, 'display_name', None) or inter.user.name
            color_map = {
                'Approved': discord.Color.green(),
                'Denied':   discord.Color.red(),
                'Discuss':  discord.Color.gold(),
            }
            title_map = {
                'Approved': 'Sheet Approved',
                'Denied':   'Sheet Denied',
                'Discuss':  'Please Contact Staff',
            }

            result_embeds, _ = _build_embeds(
                char_name, act, fields, reviewer_name,
                title=title_map.get(act, act),
                color=color_map.get(act, discord.Color.default()),
                comment=comment,
            )

            guild_id = str(inter.guild.id) if inter.guild else '0'
            channels = get_channel_ids(guild_id)
            member_channel = bot.get_channel(int(channels['member'])) if channels.get('member') else None
            if isinstance(member_channel, discord.TextChannel) and result_embeds:
                await member_channel.send(content=f"<@{mid}>", embeds=result_embeds)

            await inter.response.send_message(
                f"Sheet marked as **{act}**.", ephemeral=True
            )
        except Exception as e:
            try:
                await inter.response.send_message(f"Error processing review: {e}", ephemeral=True)
            except Exception:
                pass

    await interaction.response.send_modal(
        _ImportReviewModal(action, storage_sheet_id, member_id, apply_action)
    )


# --- Bot initialization and event handlers ---

def setup_bot():
    """Initialize bot event handlers and load extensions."""

    @bot.event
    async def on_ready():
        """Called when the bot successfully connects to Discord."""
        print(f'✓ Bot logged in as {bot.user}')

        inserted = ensure_server_rows_for_guilds(list(bot.guilds))
        if inserted:
            print(f'✓ Created {inserted} blank Server row(s) in Settings.db')
        else:
            print('✓ Server rows already present for all guilds')

        try:
            synced = await bot.tree.sync()
            print(f'✓ Synced {len(synced)} slash commands')
        except Exception as e:
            print(f'✗ Failed to sync slash commands: {e}')

    @bot.event
    async def on_guild_join(guild: discord.Guild):
        """Create a blank Server row when the bot joins a new guild."""
        if ensure_server_row(guild.id):
            print(f'✓ Created blank Server row for new guild: {guild.name} ({guild.id})')
        else:
            print(f'✓ Server row already existed for guild: {guild.name} ({guild.id})')

    @bot.event
    async def on_interaction(interaction: discord.Interaction):
        """Route component interactions and audit slash command invocations."""
        try:
            # Handle import-review buttons sent by the web server
            if interaction.type == discord.InteractionType.component:
                custom_id = (interaction.data or {}).get('custom_id', '')
                if custom_id.startswith('import_rev:'):
                    await _handle_import_review_button(interaction)
                    return

            if interaction.type == discord.InteractionType.application_command:
                data = getattr(interaction, 'data', {}) or {}
                command_name = data.get('name') or 'unknown'
                actor = f"{interaction.user} ({interaction.user.id})"
                route = f'/discord/{command_name}'
                details = build_discord_interaction_details(interaction, command_name=command_name)
                details['phase'] = 'invoked'
                write_discord_audit_log(
                    actor=actor,
                    route=route,
                    action='discord_command_invoked',
                    request_details=details,
                    response_status=200,
                )
        except Exception:
            pass

    @bot.event
    async def on_app_command_error(interaction: discord.Interaction, error: Exception):
        """Audit slash command failures."""
        try:
            data = getattr(interaction, 'data', {}) or {}
            command_name = data.get('name') or 'unknown'
            actor = f"{interaction.user} ({interaction.user.id})"
            route = f'/discord/{command_name}'
            details = build_discord_interaction_details(interaction, command_name=command_name)
            details['phase'] = 'error'
            details['error'] = str(error)
            write_discord_audit_log(
                actor=actor,
                route=route,
                action='discord_command_error',
                request_details=details,
                response_status=500,
            )
        except Exception:
            pass

    import importlib
    importlib.import_module('commands.Config')

    async def main():
        """Load all extensions and start the bot."""
        token = get_discord_token()
        if not token:
            raise RuntimeError("DISCORD_TOKEN is not set in Discord_Bot/.env.")

        print("Loading extensions:")
        await bot.load_extension('commands.Config')
        print("  ✓ Config")
        await bot.load_extension('commands.Inventory')
        print("  ✓ Inventory")
        await bot.load_extension('commands.Sheets')
        print("  ✓ Sheets  (Sheet + Search)")
        await bot.load_extension('commands.Economy')
        print("  ✓ Economy  (Currency + Trade + Work)")
        await bot.load_extension('commands.Market')
        print("  ✓ Market   (Items + Shop)")
        await bot.load_extension('commands.Combat')
        print("  ✓ Combat   (Fight + HealthBar + Death)")
        await bot.load_extension('commands.Help')
        print("  ✓ Help")
        print("✓ All extensions loaded successfully!\n")

        print("Starting bot...")
        await bot.start(token)
    return main

if __name__ == "__main__":
    # Clear the terminal for clean logs
    os.system('cls' if os.name == 'nt' else 'clear')
    print("=" * 50)
    print("Initializing Discord Bot...")
    print("=" * 50 + "\n")

    main_fn = setup_bot()
    main_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(main_loop)
    try:
        main_loop.run_until_complete(main_fn())
    except KeyboardInterrupt:
        print("\n✓ Bot shutdown requested (Ctrl+C pressed)")
    except Exception as e:
        print(f"\n✗ Bot encountered an error: {e}")
        raise
    finally:
        print("✓ Cleanup complete")
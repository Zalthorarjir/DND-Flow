import sqlite3
import discord
from discord import app_commands
from discord.ext import commands
import os
from typing import Optional, cast

from .sheet_storage import (
    add_template_field,
    remove_template_field,
    get_template,
    clear_template,
    ensure_schema,
    get_character,
    delete_character,
    search_characters,
)

DB_PATH = os.path.join('databases', 'Settings.db')


class Config(commands.Cog):


    # ...existing code...

    async def is_admin(self, interaction: discord.Interaction) -> bool:
        """Check if the user has the admin role configured in Settings.db."""
        guild = interaction.guild
        user = interaction.user
        if not guild or not user:
            return False
        # Guild owners must always be able to use /config commands.
        if getattr(user, 'id', None) == getattr(guild, 'owner_id', None):
            return True
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT admin_role_id FROM Server WHERE guild_id=?', (guild.id,))
        row = c.fetchone()
        conn.close()
        admin_role_id = row[0] if row else None
        if not admin_role_id:
            return False
        admin_role = guild.get_role(admin_role_id)
        return admin_role is not None and admin_role in getattr(user, 'roles', [])
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ensure_tables()
        self.tree = bot.tree

    config = app_commands.Group(name="config", description="Configuration commands for server and sheets.")
    field = app_commands.Group(name="field", description="Manage sheet fields.")
    config.add_command(field)

    def ensure_tables(self):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS Server (
            guild_id INTEGER PRIMARY KEY,
            admin_role_id INTEGER,
            admin_channel_id INTEGER,
            member_role_id INTEGER,
            member_channel_id INTEGER
        )''')
        conn.commit()
        conn.close()
        ensure_schema()

    @config.command(name="role", description="Set admin/member role.")
    @app_commands.describe(role_type="admin or member", role="Role to set")
    @app_commands.choices(role_type=[
        app_commands.Choice(name="admin", value="admin"),
        app_commands.Choice(name="member", value="member")
    ])
    async def role(self, interaction: discord.Interaction, role_type: app_commands.Choice[str], role: discord.Role):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        if not await self.is_admin(interaction):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT * FROM Server WHERE guild_id=?', (guild.id,))
        exists = c.fetchone()
        _role_cols = {"admin": "admin_role_id", "member": "member_role_id"}
        col = _role_cols[role_type.value]
        if exists:
            c.execute(f'UPDATE Server SET {col}=? WHERE guild_id=?', (role.id, guild.id))
        else:
            c.execute(f'INSERT INTO Server (guild_id, {col}) VALUES (?, ?)', (guild.id, role.id))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f'{role_type.value.capitalize()} role set to {role.name}.', ephemeral=True)


    @config.command(name="channel", description="Set admin/member channel.")
    @app_commands.describe(channel_type="admin or member", channel="Channel to set")
    @app_commands.choices(channel_type=[
        app_commands.Choice(name="admin", value="admin"),
        app_commands.Choice(name="member", value="member")
    ])
    async def channel(self, interaction: discord.Interaction, channel_type: app_commands.Choice[str], channel: discord.TextChannel):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        if not await self.is_admin(interaction):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT * FROM Server WHERE guild_id=?', (guild.id,))
        exists = c.fetchone()
        _chan_cols = {"admin": "admin_channel_id", "member": "member_channel_id"}
        col = _chan_cols[channel_type.value]
        if exists:
            c.execute(f'UPDATE Server SET {col}=? WHERE guild_id=?', (channel.id, guild.id))
        else:
            c.execute(f'INSERT INTO Server (guild_id, {col}) VALUES (?, ?)', (guild.id, channel.id))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f'{channel_type.value.capitalize()} channel set to {channel.mention}.', ephemeral=True)

    async def fieldname_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        guild = interaction.guild
        if not guild:
            return []
        template = get_template(str(guild.id))
        return [
            app_commands.Choice(name=t['field_name'], value=t['field_name'])
            for t in template
            if current.lower() in t['field_name'].lower()
        ][:25]

    async def admin_char_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        """Autocomplete character names scoped to the user selected in the same command."""
        guild = interaction.guild
        if not guild:
            return []
        # Read the user argument already typed by the admin
        ns = interaction.namespace
        target_user: Optional[discord.Member] = getattr(ns, 'user', None)
        user_id = str(target_user.id) if target_user else None
        results = search_characters(str(guild.id), name_query=current, user_id=user_id)
        return [
            app_commands.Choice(name=r['name'], value=r['name'])
            for r in results
        ][:25]

    @field.command(name="add", description="Add a field to the guild sheet template.")
    @app_commands.describe(fieldname="Field name to add", required="Mark this field as required on submission")
    async def field_add(self, interaction: discord.Interaction, fieldname: str, required: bool = False):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        if not await self.is_admin(interaction):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return
        guild_id = str(guild.id)
        existing = get_template(guild_id)
        next_order = max((t['sort_order'] for t in existing), default=-1) + 1
        add_template_field(guild_id, fieldname, sort_order=next_order, required=int(required))
        req_label = " (required)" if required else ""
        await interaction.response.send_message(f'Field **"{fieldname}"** added to the sheet template{req_label}.', ephemeral=True)

    @field.command(name="remove", description="Remove a field from the guild sheet template.")
    @app_commands.describe(fieldname="Field name to remove")
    @app_commands.autocomplete(fieldname=fieldname_autocomplete)
    async def field_remove(self, interaction: discord.Interaction, fieldname: str):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        if not await self.is_admin(interaction):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return
        remove_template_field(str(guild.id), fieldname)
        await interaction.response.send_message(f'Field **"{fieldname}"** removed from the sheet template.', ephemeral=True)

    @config.command(name="delete", description="[Admin] Permanently delete a user's character and sheet.")
    @app_commands.describe(user="The user who owns the character", name="Exact character name")
    @app_commands.autocomplete(name=admin_char_autocomplete)
    async def delete_character_cmd(self, interaction: discord.Interaction, user: discord.Member, name: str):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        if not await self.is_admin(interaction):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        char = get_character(str(user.id), str(guild.id), name)
        if not char:
            await interaction.response.send_message(
                f"No character named **{name}** found for {user.mention}.", ephemeral=True
            )
            return

        delete_character(char["character_id"])
        await interaction.response.send_message(
            f"Character **{name}** belonging to {user.mention} has been permanently deleted.",
            ephemeral=True,
        )

    @config.command(name="reset", description="Reset Sheets, Roles, Fields, or Channels.")
    @app_commands.describe(target="What to reset: Sheets, Roles, Fields, Channels")
    @app_commands.choices(target=[
        app_commands.Choice(name="Sheets", value="sheets"),
        app_commands.Choice(name="Roles", value="roles"),
        app_commands.Choice(name="Fields", value="fields"),
        app_commands.Choice(name="Channels", value="channels")
    ])
    async def reset(self, interaction: discord.Interaction, target: app_commands.Choice[str]):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return
        if not await self.is_admin(interaction):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        if target.value in ('sheets', 'fields'):
            conn.close()
            clear_template(str(guild.id))
            await interaction.response.send_message('All sheet template fields cleared.', ephemeral=True)
            return
        elif target.value == 'roles':
            c.execute('UPDATE Server SET admin_role_id=NULL, member_role_id=NULL WHERE guild_id=?', (guild.id,))
            await interaction.response.send_message('Roles reset.', ephemeral=True)
        elif target.value == 'channels':
            c.execute('UPDATE Server SET admin_channel_id=NULL, member_channel_id=NULL WHERE guild_id=?', (guild.id,))
            await interaction.response.send_message('Channels reset.', ephemeral=True)
        else:
            await interaction.response.send_message('Invalid reset target.', ephemeral=True)
        conn.commit()
        conn.close()

# Standalone work_cooldown command for /config work_cooldown
@app_commands.command(name="work_cooldown", description="Set the work cooldown time in days (0 = no cooldown)")
@app_commands.describe(days="Cooldown time in days (0 for no cooldown)")
async def work_cooldown(interaction: discord.Interaction, days: int):
    bot = interaction.client
    if not isinstance(bot, commands.Bot):
        await interaction.response.send_message("Bot instance not found.", ephemeral=True)
        return
    cog = bot.get_cog("Config")
    from .Config import Config as ConfigCog
    cog = cast(ConfigCog, cog)
    if not cog or not await cog.is_admin(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    if days < 0:
        await interaction.response.send_message("Cooldown days must be zero or a positive number.", ephemeral=True)
        return
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS WorkCooldown (
            guild_id TEXT PRIMARY KEY,
            days INTEGER
        )
    """)
    c.execute('INSERT OR REPLACE INTO WorkCooldown (guild_id, days) VALUES (?, ?)', (str(guild.id), days))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"Work cooldown set to {days} day(s).", ephemeral=True)

async def setup(bot):
    cog = Config(bot)
    await bot.add_cog(cog)
    # Dynamically import and add DeathConfig and Death cogs to avoid circular import
    import importlib
    death_mod = importlib.import_module('commands.Combat')
    #await bot.add_cog(death_mod.DeathConfig(bot))
    #await bot.add_cog(death_mod.Death(bot))
    # Only add config group if not already present
    if not any(cmd.name == cog.config.name for cmd in bot.tree.get_commands()):
        bot.tree.add_command(cog.config)
    # Add work_cooldown as a subcommand of config
    cog.config.add_command(work_cooldown)
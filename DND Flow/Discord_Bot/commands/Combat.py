###############################################################
# Combat.py — Fight system, HP tracking, and Death cooldowns #
# Merges: fight_dynamic.py, healthbar.py, Death.py           #
###############################################################

import os
import sqlite3
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import random
import time

from .Config import Config
from .Inventory import find_user_db_by_name, get_user_id_from_mention

# ─── Constants ───────────────────────────────────────────────────────────────

_BASE      = os.path.dirname(os.path.dirname(__file__))
COMBAT_DB  = os.path.join(_BASE, 'databases', 'Combat.db')
USERS_DIR  = os.path.join(_BASE, 'databases', 'Users')

# ─── Fight helpers ───────────────────────────────────────────────────────────

def _guild_scope_id(guild: Optional[discord.abc.Snowflake]) -> Optional[str]:
    return str(guild.id) if guild and getattr(guild, 'id', None) else None


def get_combat_weights(guild_id: Optional[str]):
    conn = sqlite3.connect(COMBAT_DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS Rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT NOT NULL,
        hitchance REAL, missed1 REAL, missed2 REAL, missed3 REAL
    )''')
    if guild_id:
        c.execute('SELECT hitchance, missed1, missed2, missed3 FROM Rules WHERE guild_id=? ORDER BY id DESC LIMIT 1', (guild_id,))
    else:
        c.execute('SELECT hitchance, missed1, missed2, missed3 FROM Rules ORDER BY id DESC LIMIT 1')
    row = c.fetchone()
    conn.close()
    return list(row) if row else [0.25, 0.25, 0.25, 0.25]

def set_combat_weights(guild_id: Optional[str], hitchance, missed1, missed2, missed3):
    conn = sqlite3.connect(COMBAT_DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS Rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT NOT NULL,
        hitchance REAL, missed1 REAL, missed2 REAL, missed3 REAL
    )''')
    c.execute('INSERT INTO Rules (guild_id, hitchance, missed1, missed2, missed3) VALUES (?, ?, ?, ?, ?)',
              (guild_id, hitchance, missed1, missed2, missed3))
    conn.commit()
    conn.close()

# ─── Death helpers ───────────────────────────────────────────────────────────

def ensure_death_table():
    conn = sqlite3.connect(COMBAT_DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS DeathCooldown (
        user_id TEXT NOT NULL,
        guild_id TEXT NOT NULL DEFAULT "",
        name TEXT NOT NULL,
        cooldown INTEGER,
        infinite INTEGER DEFAULT 0,
        set_at INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, guild_id, name)
    )''')
    cols = {row[1] for row in c.execute('PRAGMA table_info(DeathCooldown)').fetchall()}
    if 'guild_id' not in cols:
        c.execute('ALTER TABLE DeathCooldown RENAME TO DeathCooldown_legacy')
        c.execute('''CREATE TABLE DeathCooldown (
            user_id TEXT NOT NULL,
            guild_id TEXT NOT NULL DEFAULT "",
            name TEXT NOT NULL,
            cooldown INTEGER,
            infinite INTEGER DEFAULT 0,
            set_at INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, guild_id, name)
        )''')
        c.execute(
            'INSERT INTO DeathCooldown (user_id, guild_id, name, cooldown, infinite, set_at) '
            'SELECT user_id, "", name, cooldown, infinite, set_at FROM DeathCooldown_legacy'
        )
        c.execute('DROP TABLE DeathCooldown_legacy')
    c.execute('''CREATE TABLE IF NOT EXISTS GlobalSettings (
        guild_id TEXT PRIMARY KEY, cooldown INTEGER DEFAULT 0, infinite INTEGER DEFAULT 0
    )''')
    conn.commit()
    conn.close()

# ─── Admin check helper ───────────────────────────────────────────────────────

async def _admin_check(interaction: discord.Interaction) -> bool:
    bot = interaction.client
    if not isinstance(bot, commands.Bot):
        await interaction.response.send_message("Bot instance not found.", ephemeral=True)
        return False
    config_cog = bot.get_cog("Config")
    is_admin = getattr(config_cog, "is_admin", None)
    if not config_cog or not is_admin or not (await is_admin(interaction)):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return False
    return True

# ═══════════════════════════════════════════════════════════════════════════════
# FightDynamic Cog
# ═══════════════════════════════════════════════════════════════════════════════

class FightDynamic(commands.GroupCog):
    group = app_commands.Group(name="fight_dynamic", description="Fight dynamic commands.")

    def __init__(self, bot):
        self.bot = bot
        self.fight_data = {}

    @app_commands.command(name='dynamic', description='Start a fight between two OCs (character-based, not member-based)')
    @app_commands.describe(
        oc="Your character name",
        opponent="Opponent (mention)",
        opponentoc="Opponent's character name"
    )
    async def fight_dynamic(self, interaction: discord.Interaction, oc: str, opponent: discord.Member, opponentoc: str):
        user_id = str(interaction.user.id)
        opponent_id = str(opponent.id)
        guild_id = _guild_scope_id(interaction.guild)
        user_table = find_user_db_by_name(USERS_DIR, oc, user_id, guild_id=guild_id)
        if not user_table:
            await interaction.response.send_message(f'No character found with name {oc} for you.', ephemeral=True)
            return
        opponent_table = find_user_db_by_name(USERS_DIR, opponentoc, opponent_id, guild_id=guild_id)
        if not opponent_table:
            await interaction.response.send_message(f'No character found with name {opponentoc} for {opponent.display_name}.', ephemeral=True)
            return
        embed = discord.Embed(
            title=f"{oc} (by {interaction.user.display_name}) vs {opponentoc} (by {opponent.display_name})",
            description="A fight has started! React with 🗡️ to attack.",
            color=discord.Color.red()
        )
        embed.add_field(name=oc, value="Health: 20", inline=True)
        embed.add_field(name=opponentoc, value="Health: 20", inline=True)
        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()
        await message.add_reaction("🗡️")
        self.fight_data[message.id] = {
            "challenger": interaction.user,
            "opponent": opponent,
            "challenger_health": 20,
            "opponent_health": 20,
            "turn": interaction.user,
            "interaction": interaction,
            "challenger_oc": oc,
            "opponent_oc": opponentoc
        }

    @app_commands.command(name='rules', description='Set the chances for the attack outcomes (admin only)')
    @app_commands.describe(
        solid_hit="Chance to hit (-2 HP) 1=High chance, 0=Not possible.",
        small_hit="Chance for small hit (-1 HP) 1=High chance, 0=Not possible.",
        missed="Chance for miss (-0 HP) 1=High chance, 0=Not possible.",
        self_hit="Chance for self-hit (-1 HP) 1=High chance, 0=Not possible."
    )
    async def fight_dynamic_rules(self, interaction: discord.Interaction, solid_hit: float, small_hit: float, missed: float, self_hit: float):
        if not await _admin_check(interaction):
            return
        set_combat_weights(_guild_scope_id(interaction.guild), solid_hit, small_hit, missed, self_hit)
        await interaction.response.send_message(f"Fight dynamic rules updated: {[solid_hit, small_hit, missed, self_hit]}")

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot:
            return
        message_id = reaction.message.id
        if message_id not in self.fight_data:
            return
        fight = self.fight_data[message_id]
        if reaction.emoji != "🗡️":
            return
        if user != fight["turn"]:
            interaction = fight["interaction"]
            await interaction.followup.send(f"{user.mention}, it is not your turn yet!", ephemeral=True)
            await reaction.remove(user)
            return
        weights = get_combat_weights(_guild_scope_id(reaction.message.guild))
        if user == fight["challenger"]:
            attacker_name = fight["challenger_oc"]
            defender_name = fight["opponent_oc"]
        else:
            attacker_name = fight["opponent_oc"]
            defender_name = fight["challenger_oc"]
        outcomes = [
            f"**{attacker_name}** landed a solid hit!",
            f"**{attacker_name}** barely scratched {defender_name}. Better luck next time!",
            f"**{attacker_name}** missed completely. What a blunder!",
            f"**{attacker_name}** missed and ended up hitting themselves. Ouch!"
        ]
        outcome = random.choices(outcomes, weights=weights, k=1)[0]
        if user == fight["challenger"]:
            if outcome == outcomes[0]:
                fight["opponent_health"] -= 2
            elif outcome == outcomes[1]:
                fight["opponent_health"] -= 1
            elif outcome == outcomes[3]:
                fight["challenger_health"] -= 1
            fight["turn"] = fight["opponent"]
        else:
            if outcome == outcomes[0]:
                fight["challenger_health"] -= 2
            elif outcome == outcomes[1]:
                fight["challenger_health"] -= 1
            elif outcome == outcomes[3]:
                fight["opponent_health"] -= 1
            fight["turn"] = fight["challenger"]
        embed = reaction.message.embeds[0]
        embed.set_field_at(0, name=fight["challenger_oc"], value=f"Health: {fight['challenger_health']}", inline=True)
        embed.set_field_at(1, name=fight["opponent_oc"], value=f"Health: {fight['opponent_health']}", inline=True)
        embed.description = outcome
        await reaction.message.edit(embed=embed)
        await reaction.message.clear_reactions()
        await reaction.message.add_reaction("🗡️")
        if fight["challenger_health"] <= 0 or fight["opponent_health"] <= 0:
            winner = fight["challenger"] if fight["challenger_health"] > 0 else fight["opponent"]
            await reaction.message.channel.send(f"{winner.mention} wins the fight!")
            del self.fight_data[message_id]


# ═══════════════════════════════════════════════════════════════════════════════
# HealthBar Cog
# ═══════════════════════════════════════════════════════════════════════════════

class HealthBar(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.health_data = {}  # message_id: { 'table', 'name', 'hp', 'max_hp' }

    @app_commands.command(name='health_track', description='Track HP for a character by name (uses character table, not member)')
    @app_commands.describe(name="Character name", hp="Starting/max HP")
    async def health_track(self, interaction: discord.Interaction, name: str, hp: int):
        user_id = str(interaction.user.id)
        guild_id = _guild_scope_id(interaction.guild)
        table_name = find_user_db_by_name(USERS_DIR, name, user_id, guild_id=guild_id)
        if not table_name:
            await interaction.response.send_message(f'No character found with name {name} for you.', ephemeral=True)
            return
        embed = discord.Embed(title=name, description=f"Has {hp} HP\n{'❤️' * hp}")
        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()
        self.health_data[message.id] = {'table': table_name, 'name': name, 'hp': hp, 'max_hp': hp}
        await message.add_reaction('⬇️')
        await message.add_reaction('⬆️')
        await message.add_reaction('💀')

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot:
            return
        message_id = reaction.message.id
        if message_id not in self.health_data:
            return
        health_info = self.health_data[message_id]
        if reaction.emoji == '⬇️':
            health_info['hp'] = max(0, health_info['hp'] - 1)
        elif reaction.emoji == '⬆️':
            health_info['hp'] = min(health_info['max_hp'], health_info['hp'] + 1)
        elif reaction.emoji == '💀':
            await reaction.message.delete()
            del self.health_data[message_id]
            return
        embed = discord.Embed(title=health_info['name'], description=f"Has {health_info['hp']} HP\n{'❤️' * health_info['hp']}")
        await reaction.message.edit(embed=embed)
        await reaction.remove(user)


# ═══════════════════════════════════════════════════════════════════════════════
# Death Cog
# ═══════════════════════════════════════════════════════════════════════════════

class Death(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        ensure_death_table()

    death = app_commands.Group(name="death", description="Death cooldown configuration and checks.")

    @death.command(name="claim", description="Claim a character's death for approval.")
    @app_commands.describe(mention="User mention", name="Character/Inventory name")
    async def claim(self, interaction: discord.Interaction, mention: str, name: str):
        guild_id = _guild_scope_id(interaction.guild)
        user_id = get_user_id_from_mention(mention)
        table_name = find_user_db_by_name(USERS_DIR, name, user_id, guild_id=guild_id)
        if not table_name:
            await interaction.response.send_message(f'No character found with name {name} for user {mention}.', ephemeral=True)
            return
        config_cog = self.bot.get_cog("Config")
        admin_channel_id = None
        guild = interaction.guild
        if config_cog and guild:
            conn = sqlite3.connect(os.path.join('databases', 'Settings.db'))
            c = conn.cursor()
            c.execute('SELECT admin_channel_id FROM Server WHERE guild_id=?', (guild.id,))
            row = c.fetchone()
            conn.close()
            if row and row[0]:
                admin_channel_id = row[0]
        admin_channel = None
        if admin_channel_id and guild:
            channel = guild.get_channel(admin_channel_id)
            if isinstance(channel, discord.TextChannel):
                admin_channel = channel
        if not admin_channel:
            await interaction.response.send_message("Admin channel is not set or is not a text channel. Please contact an admin.", ephemeral=True)
            return
        invoked_in = getattr(interaction.channel, "mention", "(unknown)")
        embed = discord.Embed(title="Death Claim Request", color=discord.Color.orange())
        embed.add_field(name="Invoked By", value=interaction.user.mention, inline=False)
        embed.add_field(name="Invoked In", value=invoked_in, inline=False)
        embed.add_field(name="Target User", value=mention, inline=True)
        embed.add_field(name="Character Name", value=name, inline=True)
        embed.set_footer(text=f"User ID: {user_id}")

        class ClaimView(discord.ui.View):
            def __init__(self, invoker_id, target_id, char_name, orig_channel_id):
                super().__init__(timeout=3600)
                self.invoker_id = invoker_id
                self.target_id = target_id
                self.char_name = char_name
                self.orig_channel_id = orig_channel_id

            @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
            async def approve(self, interaction_button: discord.Interaction, button: discord.ui.Button):
                if not await _admin_check(interaction_button):
                    return
                guild_id = _guild_scope_id(interaction_button.guild)
                table_name = find_user_db_by_name(USERS_DIR, self.char_name, self.target_id, guild_id=guild_id)
                if not table_name:
                    await interaction_button.response.send_message(f'No character table found for {self.char_name} (user <@{self.target_id}>).', ephemeral=True)
                    return
                ensure_death_table()
                conn = sqlite3.connect(COMBAT_DB)
                c = conn.cursor()
                c.execute('SELECT cooldown, infinite FROM GlobalSettings WHERE guild_id=?', (guild_id,))
                row = c.fetchone()
                cooldown_days, infinite = row if row else (0, 0)
                set_at = int(time.time())
                c.execute('INSERT OR REPLACE INTO DeathCooldown (user_id, guild_id, name, cooldown, infinite, set_at) VALUES (?, ?, ?, ?, ?, ?)',
                          (str(self.target_id), str(guild_id or ''), table_name, cooldown_days, infinite, set_at))
                conn.commit()
                conn.close()
                guild = interaction_button.guild
                orig_channel = guild.get_channel(self.orig_channel_id) if guild else None
                if not (isinstance(orig_channel, discord.TextChannel) or isinstance(orig_channel, discord.Thread)):
                    orig_channel = None
                invoker = guild.get_member(self.invoker_id) if guild else None
                target = guild.get_member(self.target_id) if guild else None
                result_embed = discord.Embed(title="Death Claim Approved", color=discord.Color.green())
                result_embed.add_field(name="Character Name", value=self.char_name, inline=True)
                result_embed.add_field(name="Target User", value=target.mention if target else f"<@{self.target_id}>", inline=True)
                cooldown_str = "Infinite" if infinite else f"{cooldown_days} day(s)"
                result_embed.add_field(name="Death Cooldown Applied", value=cooldown_str, inline=True)
                result_embed.add_field(name="Approved By", value=interaction_button.user.mention, inline=False)
                result_embed.add_field(name="Requested By", value=invoker.mention if invoker else f"<@{self.invoker_id}>", inline=False)
                await interaction_button.response.send_message("Death claim approved.", ephemeral=True)
                if orig_channel:
                    invoker_tag = invoker.mention if invoker else f"<@{self.invoker_id}>"
                    target_tag = target.mention if target else f"<@{self.target_id}>"
                    await orig_channel.send(content=f"{invoker_tag} {target_tag}", embed=result_embed)
                self.stop()

            @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
            async def deny(self, interaction_button: discord.Interaction, button: discord.ui.Button):
                if not await _admin_check(interaction_button):
                    return
                guild = interaction_button.guild
                orig_channel = guild.get_channel(self.orig_channel_id) if guild else None
                if not (isinstance(orig_channel, discord.TextChannel) or isinstance(orig_channel, discord.Thread)):
                    orig_channel = None
                invoker = guild.get_member(self.invoker_id) if guild else None
                target = guild.get_member(self.target_id) if guild else None
                result_embed = discord.Embed(title="Death Claim Denied", color=discord.Color.red())
                result_embed.add_field(name="Character Name", value=self.char_name, inline=True)
                result_embed.add_field(name="Target User", value=target.mention if target else f"<@{self.target_id}>", inline=True)
                result_embed.add_field(name="Denied By", value=interaction_button.user.mention, inline=False)
                result_embed.add_field(name="Requested By", value=invoker.mention if invoker else f"<@{self.invoker_id}>", inline=False)
                await interaction_button.response.send_message("Death claim denied.", ephemeral=True)
                if orig_channel:
                    invoker_tag = invoker.mention if invoker else f"<@{self.invoker_id}>"
                    target_tag = target.mention if target else f"<@{self.target_id}>"
                    await orig_channel.send(content=f"{invoker_tag} {target_tag}", embed=result_embed)
                self.stop()

        orig_channel_id = getattr(interaction.channel, "id", None)
        view = ClaimView(invoker_id=interaction.user.id, target_id=user_id, char_name=name, orig_channel_id=orig_channel_id)
        await admin_channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"Death claim for {mention} ({name}) sent for admin approval.", ephemeral=True)

    @death.command(name="set", description="Set the global death cooldown (in days, 0 = no cooldown)")
    @app_commands.describe(time="Cooldown in days (0 = no cooldown)")
    async def set_death(self, interaction: discord.Interaction, time: int):
        if not await _admin_check(interaction):
            return
        ensure_death_table()
        conn = sqlite3.connect(COMBAT_DB)
        c = conn.cursor()
        guild_id = _guild_scope_id(interaction.guild)
        c.execute('INSERT OR REPLACE INTO GlobalSettings (guild_id, cooldown, infinite) VALUES (?, ?, 0)', (guild_id, time))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"Global death cooldown set to {time} day(s).", ephemeral=True)

    @death.command(name="infinite", description="Set death cooldown to infinite or none.")
    @app_commands.describe(choice="Infinite or None")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Yes", value="yes"),
        app_commands.Choice(name="No", value="no")
    ])
    async def set_infinite(self, interaction: discord.Interaction, choice: app_commands.Choice[str]):
        if not await _admin_check(interaction):
            return
        ensure_death_table()
        conn = sqlite3.connect(COMBAT_DB)
        c = conn.cursor()
        guild_id = _guild_scope_id(interaction.guild)
        if choice.value == "yes":
            c.execute('INSERT OR REPLACE INTO GlobalSettings (guild_id, cooldown, infinite) VALUES (?, COALESCE((SELECT cooldown FROM GlobalSettings WHERE guild_id=?), 0), 1)', (guild_id, guild_id))
            msg = "Death cooldown set to infinite."
        else:
            c.execute('INSERT OR REPLACE INTO GlobalSettings (guild_id, cooldown, infinite) VALUES (?, COALESCE((SELECT cooldown FROM GlobalSettings WHERE guild_id=?), 0), 0)', (guild_id, guild_id))
            msg = "Death cooldown set to none."
        conn.commit()
        conn.close()
        await interaction.response.send_message(msg, ephemeral=True)

    @death.command(name="reset", description="Reset a user's death cooldown for a given name.")
    @app_commands.describe(mention="User mention", name="Character/Inventory name")
    async def reset_death(self, interaction: discord.Interaction, mention: str, name: str):
        if not await _admin_check(interaction):
            return
        guild_id = _guild_scope_id(interaction.guild)
        user_id = get_user_id_from_mention(mention)
        table_name = find_user_db_by_name(USERS_DIR, name, user_id, guild_id=guild_id)
        if not table_name:
            await interaction.response.send_message(f'No character found with name {name} for user {mention}.', ephemeral=True)
            return
        ensure_death_table()
        conn = sqlite3.connect(COMBAT_DB)
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO DeathCooldown (user_id, guild_id, name, cooldown, infinite, set_at) VALUES (?, ?, ?, 0, 0, ?)',
                  (user_id, str(guild_id or ''), table_name, int(time.time())))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"Death cooldown for {name} ({mention}) reset to 0.", ephemeral=True)

    @death.command(name="check", description="Check your death cooldown for a given name.")
    @app_commands.describe(name="Character/Inventory name")
    async def check(self, interaction: discord.Interaction, name: str):
        user_id = str(interaction.user.id)
        guild_id = _guild_scope_id(interaction.guild)
        table_name = find_user_db_by_name(USERS_DIR, name, user_id, guild_id=guild_id)
        if not table_name:
            await interaction.response.send_message(f'No character found with name {name}.', ephemeral=True)
            return
        ensure_death_table()
        conn = sqlite3.connect(COMBAT_DB)
        c = conn.cursor()
        c.execute('SELECT cooldown, infinite, set_at FROM DeathCooldown WHERE user_id=? AND guild_id=? AND name=?', (user_id, str(guild_id or ''), table_name))
        row = c.fetchone()
        now = int(time.time())
        if row:
            cooldown, infinite, set_at = row
            expires_at = (set_at + cooldown * 86400) if (set_at and cooldown) else None
            remaining = max(0, (expires_at - now) // 86400) if expires_at else cooldown
        else:
            c.execute('SELECT cooldown, infinite FROM GlobalSettings WHERE guild_id=?', (guild_id,))
            global_row = c.fetchone()
            cooldown, infinite = global_row if global_row else (0, 0)
            expires_at = None
            remaining = cooldown
        conn.close()
        if infinite:
            await interaction.response.send_message(f"Death cooldown for {name}: Infinite", ephemeral=True)
        elif expires_at:
            await interaction.response.send_message(f"Death cooldown for {name}: {remaining} day(s) left (<t:{expires_at}:R>)", ephemeral=True)
        else:
            await interaction.response.send_message(f"Death cooldown for {name}: {cooldown} day(s)", ephemeral=True)

    @death.command(name="revive", description="Revive a character if eligible (cooldown 0 and not infinite)")
    @app_commands.describe(name="Character/Inventory name")
    async def revive(self, interaction: discord.Interaction, name: str):
        user_id = str(interaction.user.id)
        guild_id = _guild_scope_id(interaction.guild)
        table_name = find_user_db_by_name(USERS_DIR, name, user_id, guild_id=guild_id)
        if not table_name:
            await interaction.response.send_message(f'No character found with name {name}.', ephemeral=True)
            return
        ensure_death_table()
        conn = sqlite3.connect(COMBAT_DB)
        c = conn.cursor()
        c.execute('SELECT cooldown, infinite, set_at FROM DeathCooldown WHERE user_id=? AND guild_id=? AND name=?', (user_id, str(guild_id or ''), table_name))
        row = c.fetchone()
        now = int(time.time())
        if not row:
            conn.close()
            await interaction.response.send_message(f'No death cooldown entry found for {name}.', ephemeral=True)
            return
        cooldown_days, infinite, set_at = row
        expires_at = (set_at + cooldown_days * 86400) if (set_at and cooldown_days) else None
        if infinite:
            conn.close()
            await interaction.response.send_message(f"{name} cannot be revived.\nReason: Infinite is enabled, you can not revive.", ephemeral=True)
            return
        if cooldown_days == 0 and not infinite:
            c.execute('DELETE FROM DeathCooldown WHERE user_id=? AND guild_id=? AND name=?', (user_id, str(guild_id or ''), table_name))
            conn.commit()
            conn.close()
            await interaction.response.send_message(f"{name} has been revived.", ephemeral=True)
            return
        if expires_at and now >= expires_at:
            c.execute('DELETE FROM DeathCooldown WHERE user_id=? AND guild_id=? AND name=?', (user_id, str(guild_id or ''), table_name))
            conn.commit()
            conn.close()
            await interaction.response.send_message(f"{name} has been revived.", ephemeral=True)
        else:
            conn.close()
            reason = f"Cooldown expires <t:{expires_at}:R>" if expires_at else "No valid cooldown timestamp."
            await interaction.response.send_message(f"{name} cannot be revived.\nReason: {reason}", ephemeral=True)

    @death.command(name="list", description="List your death records.")
    async def list_deaths(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        guild_id = _guild_scope_id(interaction.guild)
        ensure_death_table()
        conn = sqlite3.connect(COMBAT_DB)
        c = conn.cursor()
        c.execute('SELECT name FROM DeathCooldown WHERE user_id=? AND guild_id=?', (user_id, str(guild_id or '')))
        rows = c.fetchall()
        conn.close()
        if not rows:
            await interaction.response.send_message("You have no death records.", ephemeral=True)
            return
        user_db_path = os.path.join(USERS_DIR, f"{user_id}.db")
        char_names = []
        if os.path.exists(user_db_path):
            uconn = sqlite3.connect(user_db_path)
            uc = uconn.cursor()
            for (table_name,) in rows:
                try:
                    uc.execute(f"SELECT Data FROM '{table_name}' WHERE [Field name]='Name' LIMIT 1")
                    name_row = uc.fetchone()
                    if name_row:
                        char_names.append(name_row[0])
                except Exception:
                    continue
            uconn.close()
        embed = discord.Embed(title="Death Records", color=discord.Color.dark_red())
        if char_names:
            embed.add_field(name="Username:", value=f"<@{user_id}>", inline=True)
            embed.add_field(name="Characters:", value="\n".join(char_names), inline=True)
        else:
            embed.description = "No character names found."
        embed.set_footer(text=f"Total: {len(char_names)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @death.command(name="graveyard", description="List all death records (all users).")
    async def graveyard(self, interaction: discord.Interaction):
        guild_id = _guild_scope_id(interaction.guild)
        ensure_death_table()
        conn = sqlite3.connect(COMBAT_DB)
        c = conn.cursor()
        c.execute('SELECT user_id, name FROM DeathCooldown WHERE guild_id=?', (str(guild_id or ''),))
        rows = c.fetchall()
        conn.close()
        if not rows:
            await interaction.response.send_message("No death records found.", ephemeral=True)
            return
        user_char_map = {}
        count = 0
        for user_id, table_name in rows:
            user_db_path = os.path.join(USERS_DIR, f"{user_id}.db")
            if os.path.exists(user_db_path):
                try:
                    uconn = sqlite3.connect(user_db_path)
                    uc = uconn.cursor()
                    uc.execute(f"SELECT Data FROM '{table_name}' WHERE [Field name]='Name' LIMIT 1")
                    name_row = uc.fetchone()
                    if name_row:
                        user_char_map.setdefault(user_id, []).append(name_row[0])
                        count += 1
                    uconn.close()
                except Exception:
                    continue
        embed = discord.Embed(title="Graveyard", color=discord.Color.dark_grey())
        if user_char_map:
            for uid, char_list in user_char_map.items():
                embed.add_field(name="Username:", value=f"<@{uid}>", inline=True)
                embed.add_field(name="Characters:", value="\n".join(char_list), inline=True)
        else:
            embed.description = "No character names found."
        embed.set_footer(text=f"Total: {count}")
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ─── Extension setup ──────────────────────────────────────────────────────────

async def setup(bot):
    await bot.add_cog(FightDynamic(bot))
    await bot.add_cog(HealthBar(bot))
    await bot.add_cog(Death(bot))

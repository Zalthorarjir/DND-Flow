###################################################################
# Economy.py — Currency, Trading, and Work/Jobs                 #
# Merges: Currency.py, Trade.py, Work.py                        #
###################################################################

import os
import sqlite3
import time
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, cast

from .Config import Config
from .Inventory import (
    find_user_db_by_name, get_user_id_from_mention,
    fetch_items, upsert_item, remove_item, fetch_item_details,
)

# ─── Constants ────────────────────────────────────────────────────────────────

_BASE        = os.path.dirname(os.path.dirname(__file__))
USERS_DIR    = os.path.join(_BASE, 'databases', 'Users')
SHOP_DB      = os.path.join(_BASE, 'databases', 'Shop.db')
INVENTORY_DB = os.path.join(_BASE, 'databases', 'Inventory.db')
ECONOMY_DB   = os.path.join(_BASE, 'databases', 'Economy.db')
SETTINGS_DB  = os.path.join(_BASE, 'databases', 'Settings.db')

# ─── Shared helpers ───────────────────────────────────────────────────────────

def _ensure_economy_schema() -> None:
    conn = sqlite3.connect(ECONOMY_DB)
    try:
        conn.execute(
            '''CREATE TABLE IF NOT EXISTS currency (
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL DEFAULT "",
                character TEXT NOT NULL,
                amount REAL DEFAULT 0,
                PRIMARY KEY (user_id, guild_id, character)
            )'''
        )

        cols_currency = {row[1] for row in conn.execute('PRAGMA table_info(currency)').fetchall()}
        if 'guild_id' not in cols_currency:
            conn.execute('ALTER TABLE currency RENAME TO currency_legacy')
            conn.execute(
                '''CREATE TABLE currency (
                    user_id TEXT NOT NULL,
                    guild_id TEXT NOT NULL DEFAULT "",
                    character TEXT NOT NULL,
                    amount REAL DEFAULT 0,
                    PRIMARY KEY (user_id, guild_id, character)
                )'''
            )
            conn.execute(
                'INSERT INTO currency (user_id, guild_id, character, amount) '
                'SELECT user_id, "", character, amount FROM currency_legacy'
            )
            conn.execute('DROP TABLE currency_legacy')

        conn.execute(
            '''CREATE TABLE IF NOT EXISTS jobs (
                guild_id TEXT NOT NULL,
                job_name TEXT NOT NULL,
                payment REAL,
                PRIMARY KEY (guild_id, job_name)
            )'''
        )
        cols_jobs = {row[1] for row in conn.execute('PRAGMA table_info(jobs)').fetchall()}
        if 'guild_id' not in cols_jobs:
            conn.execute('ALTER TABLE jobs RENAME TO jobs_legacy')
            conn.execute(
                '''CREATE TABLE jobs (
                    guild_id TEXT NOT NULL,
                    job_name TEXT NOT NULL,
                    payment REAL,
                    PRIMARY KEY (guild_id, job_name)
                )'''
            )
            conn.execute(
                'INSERT INTO jobs (guild_id, job_name, payment) '
                'SELECT "", job_name, payment FROM jobs_legacy'
            )
            conn.execute('DROP TABLE jobs_legacy')

        conn.execute(
            '''CREATE TABLE IF NOT EXISTS user_jobs (
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL DEFAULT "",
                character TEXT NOT NULL,
                job_name TEXT,
                PRIMARY KEY (user_id, guild_id, character)
            )'''
        )
        cols_user_jobs = {row[1] for row in conn.execute('PRAGMA table_info(user_jobs)').fetchall()}
        if 'guild_id' not in cols_user_jobs:
            conn.execute('ALTER TABLE user_jobs RENAME TO user_jobs_legacy')
            conn.execute(
                '''CREATE TABLE user_jobs (
                    user_id TEXT NOT NULL,
                    guild_id TEXT NOT NULL DEFAULT "",
                    character TEXT NOT NULL,
                    job_name TEXT,
                    PRIMARY KEY (user_id, guild_id, character)
                )'''
            )
            conn.execute(
                'INSERT INTO user_jobs (user_id, guild_id, character, job_name) '
                'SELECT user_id, "", character, job_name FROM user_jobs_legacy'
            )
            conn.execute('DROP TABLE user_jobs_legacy')

        conn.execute(
            '''CREATE TABLE IF NOT EXISTS last_claim (
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL DEFAULT "",
                character TEXT NOT NULL,
                last_time INTEGER,
                PRIMARY KEY (user_id, guild_id, character)
            )'''
        )
        cols_last_claim = {row[1] for row in conn.execute('PRAGMA table_info(last_claim)').fetchall()}
        if 'guild_id' not in cols_last_claim:
            conn.execute('ALTER TABLE last_claim RENAME TO last_claim_legacy')
            conn.execute(
                '''CREATE TABLE last_claim (
                    user_id TEXT NOT NULL,
                    guild_id TEXT NOT NULL DEFAULT "",
                    character TEXT NOT NULL,
                    last_time INTEGER,
                    PRIMARY KEY (user_id, guild_id, character)
                )'''
            )
            conn.execute(
                'INSERT INTO last_claim (user_id, guild_id, character, last_time) '
                'SELECT user_id, "", character, last_time FROM last_claim_legacy'
            )
            conn.execute('DROP TABLE last_claim_legacy')

        conn.commit()
    finally:
        conn.close()


def fetch_currency(user_id: str, character: str, guild_id: str = '') -> float:
    _ensure_economy_schema()
    conn = sqlite3.connect(ECONOMY_DB)
    row = conn.execute(
        'SELECT amount FROM currency WHERE user_id=? AND guild_id=? AND character=?',
        (str(user_id), str(guild_id), character)
    ).fetchone()
    conn.close()
    return row[0] if row else 0.0

def set_currency(user_id: str, character: str, amount: float, guild_id: str = '') -> None:
    _ensure_economy_schema()
    conn = sqlite3.connect(ECONOMY_DB)
    conn.execute(
        'INSERT INTO currency (user_id, guild_id, character, amount) VALUES (?, ?, ?, ?) '
        'ON CONFLICT(user_id, guild_id, character) DO UPDATE SET amount=excluded.amount',
        (str(user_id), str(guild_id), character, amount)
    )
    conn.commit()
    conn.close()

async def _admin_check(interaction: discord.Interaction) -> bool:
    bot = interaction.client
    if not isinstance(bot, commands.Bot):
        await interaction.response.send_message("Bot instance not found.", ephemeral=True)
        return False
    config_cog = bot.get_cog("Config")
    if not config_cog or not await cast(Config, config_cog).is_admin(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return False
    return True

async def _item_autocomplete(interaction: discord.Interaction, current: str):
    try:
        guild_id = str(interaction.guild.id) if interaction.guild else None
        conn = sqlite3.connect(SHOP_DB)
        c = conn.cursor()
        if guild_id:
            c.execute('SELECT name FROM items WHERE guild_id=?', (guild_id,))
        else:
            c.execute('SELECT name FROM items')
        all_items = [row[0] for row in c.fetchall()]
        conn.close()
    except Exception:
        all_items = []
    return [app_commands.Choice(name=n, value=n) for n in all_items if current.lower() in n.lower()][:25]

async def _mention_autocomplete(interaction: discord.Interaction, current: str):
    if not interaction.guild:
        return []
    choices = []
    for member in interaction.guild.members:
        display = f"{member.display_name} ({member.name})"
        mention = member.mention
        if current.lower() in display.lower() or current in mention:
            choices.append(app_commands.Choice(name=display, value=mention))
        if len(choices) >= 25:
            break
    return choices

# ═══════════════════════════════════════════════════════════════════════════════
# /currency commands
# ═══════════════════════════════════════════════════════════════════════════════

currency_group = app_commands.Group(name="currency", description="Currency commands")

@currency_group.command(name="remove", description="Remove an amount from a user's currency.")
@app_commands.describe(mention="User mention", amount="Amount to remove", name="Character name (optional)")
async def currency_remove(interaction: discord.Interaction, mention: str, amount: float, name: Optional[str] = None):
    if not await _admin_check(interaction):
        return
    guild_id = str(interaction.guild.id) if interaction.guild else ''
    user_id = get_user_id_from_mention(mention)
    if name:
        table_name = find_user_db_by_name(USERS_DIR, name, user_id, guild_id=guild_id)
        if not table_name:
            await interaction.response.send_message(f'No character found with name {name}.', ephemeral=True)
            return
        table = table_name
    else:
        table = 'Currency'
    current = fetch_currency(user_id, table, guild_id=guild_id)
    new_amount = max(0.0, current - amount)
    set_currency(user_id, table, new_amount, guild_id=guild_id)
    await interaction.response.send_message(f"Removed {amount:,.2f} from <@{user_id}>'s currency. New amount: {new_amount:,.2f}.", ephemeral=True)

@currency_group.command(name="view", description="View a user's currency amount.")
@app_commands.describe(mention="User mention", name="Character name (optional)")
async def currency_view(interaction: discord.Interaction, mention: str, name: Optional[str] = None):
    guild_id = str(interaction.guild.id) if interaction.guild else ''
    user_id = get_user_id_from_mention(mention)
    try:
        username = (await interaction.client.fetch_user(int(user_id))).name
    except Exception:
        username = str(user_id)
    table = name if name else 'Currency'
    amount = fetch_currency(user_id, table, guild_id=guild_id)
    embed = discord.Embed(title=f"Currency for {username}")
    embed.add_field(name="Amount", value=f"{amount:,.2f}", inline=False)
    embed.set_footer(text=username)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@currency_group.command(name="set", description="Set a user's currency amount.")
@app_commands.describe(mention="User mention", amount="New amount", name="Character name (optional)")
async def currency_set(interaction: discord.Interaction, mention: str, amount: float, name: Optional[str] = None):
    if not await _admin_check(interaction):
        return
    guild_id = str(interaction.guild.id) if interaction.guild else ''
    user_id = get_user_id_from_mention(mention)
    if name:
        table_name = find_user_db_by_name(USERS_DIR, name, user_id, guild_id=guild_id)
        if not table_name:
            await interaction.response.send_message(f'No character found with name {name}.', ephemeral=True)
            return
        table = table_name
    else:
        table = 'Currency'
    set_currency(user_id, table, amount, guild_id=guild_id)
    await interaction.response.send_message(f"Set currency for <@{user_id}> to {amount:,.2f}.", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
# /work commands
# ═══════════════════════════════════════════════════════════════════════════════

work_group = app_commands.Group(name="work", description="Job and work commands")

@work_group.command(name="create", description="Create a new job with a payment amount.")
@app_commands.describe(job="Job name", payment="Wage per cooldown cycle")
async def work_create(interaction: discord.Interaction, job: str, payment: float):
    if not await _admin_check(interaction):
        return
    _ensure_economy_schema()
    guild_id = str(interaction.guild.id) if interaction.guild else ''
    conn = sqlite3.connect(ECONOMY_DB)
    conn.execute("INSERT OR REPLACE INTO jobs (guild_id, job_name, payment) VALUES (?, ?, ?)", (guild_id, job, payment))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"Job '{job}' set with payment {payment:,.2f}.", ephemeral=True)

@work_group.command(name="edit", description="Edit an existing job's payment amount.")
@app_commands.describe(job="Job name", payment="New wage per cooldown cycle")
async def work_edit(interaction: discord.Interaction, job: str, payment: float):
    if not await _admin_check(interaction):
        return
    _ensure_economy_schema()
    guild_id = str(interaction.guild.id) if interaction.guild else ''
    conn = sqlite3.connect(ECONOMY_DB)
    c = conn.cursor()
    c.execute("UPDATE jobs SET payment=? WHERE guild_id=? AND job_name=?", (payment, guild_id, job))
    if c.rowcount == 0:
        conn.close()
        await interaction.response.send_message(f"Job '{job}' does not exist.", ephemeral=True)
        return
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"Job '{job}' updated to payment {payment:,.2f}.", ephemeral=True)

@work_group.command(name="assign", description="Assign a job to a user's character.")
@app_commands.describe(job="Job name", mention="User mention", name="Character name")
async def work_assign(interaction: discord.Interaction, job: str, mention: str, name: str):
    if not await _admin_check(interaction):
        return
    _ensure_economy_schema()
    guild_id = str(interaction.guild.id) if interaction.guild else ''
    user_id = get_user_id_from_mention(mention)
    table_name = find_user_db_by_name(USERS_DIR, name, user_id, guild_id=guild_id)
    if not table_name:
        await interaction.response.send_message(f'No character found with name {name} for {mention}.', ephemeral=True)
        return
    conn = sqlite3.connect(ECONOMY_DB)
    conn.execute("INSERT OR REPLACE INTO user_jobs (user_id, guild_id, character, job_name) VALUES (?, ?, ?, ?)",
                 (user_id, guild_id, table_name, job))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"Assigned job '{job}' to {name} for {mention}.", ephemeral=True)

# ─── /job (standalone payout command) ────────────────────────────────────────

@app_commands.command(name="job", description="Claim your job payout for a character.")
@app_commands.describe(name="Character name")
async def job_claim(interaction: discord.Interaction, name: str):
    _ensure_economy_schema()
    user_id = str(interaction.user.id)
    guild_id = str(interaction.guild.id) if interaction.guild else ''
    table_name = find_user_db_by_name(USERS_DIR, name, user_id, guild_id=guild_id)
    if not table_name:
        await interaction.response.send_message(f'No character found with name {name} for you.', ephemeral=True)
        return
    conn = sqlite3.connect(ECONOMY_DB)
    row = conn.execute('SELECT job_name FROM user_jobs WHERE user_id=? AND guild_id=? AND character=?',
                       (user_id, guild_id, table_name)).fetchone()
    if not row:
        conn.close()
        await interaction.response.send_message(f'No job assigned to {name}.', ephemeral=True)
        return
    job_name = row[0]
    job_row = conn.execute('SELECT payment FROM jobs WHERE guild_id=? AND job_name=?', (guild_id, job_name)).fetchone()
    if not job_row:
        conn.close()
        await interaction.response.send_message(f'Job definition for {job_name} not found.', ephemeral=True)
        return
    payment = job_row[0]
    cooldown_days = 0
    settings_conn = sqlite3.connect(SETTINGS_DB)
    settings_row = settings_conn.execute(
        'SELECT days FROM WorkCooldown WHERE guild_id=?'
        , (guild_id,)
    ).fetchone() if settings_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='WorkCooldown'"
    ).fetchone() else None
    settings_conn.close()
    if settings_row:
        cooldown_days = settings_row[0]
    now = int(time.time())
    last_row = conn.execute('SELECT last_time FROM last_claim WHERE user_id=? AND guild_id=? AND character=?',
                            (user_id, guild_id, table_name)).fetchone()
    last_time = last_row[0] if last_row else 0
    next_time = last_time + cooldown_days * 86400
    if cooldown_days > 0 and now < next_time:
        remaining = next_time - now
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        seconds = remaining % 60
        conn.close()
        await interaction.response.send_message(f"You must wait {hours}h {minutes}m {seconds}s before claiming again.", ephemeral=True)
        return
    conn.execute('''
        INSERT INTO last_claim (user_id, guild_id, character, last_time) VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, guild_id, character) DO UPDATE SET last_time=excluded.last_time
    ''', (user_id, guild_id, table_name, now))
    conn.execute('''
        INSERT INTO currency (user_id, guild_id, character, amount) VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, guild_id, character) DO UPDATE SET amount=amount+excluded.amount
    ''', (user_id, guild_id, table_name, payment))
    conn.commit()
    new_amount = conn.execute('SELECT amount FROM currency WHERE user_id=? AND guild_id=? AND character=?',
                              (user_id, guild_id, table_name)).fetchone()[0]
    conn.close()
    await interaction.response.send_message(f"{name} claimed {payment:,.2f} for job '{job_name}'. New balance: {new_amount:,.2f}.", ephemeral=True)

# ═══════════════════════════════════════════════════════════════════════════════
# /give_money and /give_item (Trade commands)
# ═══════════════════════════════════════════════════════════════════════════════

@app_commands.command(name="give_money", description="Give currency to another user.")
@app_commands.describe(
    name="Your character name",
    amount="Amount to give",
    mention="Recipient mention",
    recipient_name="Recipient's character name"
)
@app_commands.autocomplete(mention=_mention_autocomplete)
async def give_money(interaction: discord.Interaction, name: str, amount: float, mention: str, recipient_name: str):
    _ensure_economy_schema()
    sender_id = str(interaction.user.id)
    guild_id = str(interaction.guild.id) if interaction.guild else ''
    sender_table = find_user_db_by_name(USERS_DIR, name, sender_id, guild_id=guild_id)
    if not sender_table:
        await interaction.response.send_message(f'No character found with name {name} for you.', ephemeral=True)
        return
    recipient_id = get_user_id_from_mention(mention)
    recipient_table = find_user_db_by_name(USERS_DIR, recipient_name, recipient_id, guild_id=guild_id)
    if not recipient_table:
        await interaction.response.send_message(f'No character found with name {recipient_name} for {mention}.', ephemeral=True)
        return
    conn = sqlite3.connect(ECONOMY_DB, timeout=10)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT amount FROM currency WHERE user_id=? AND guild_id=? AND character=?',
                   (sender_id, guild_id, sender_table)).fetchone()
        sender_balance = row[0] if row else 0.0
        if sender_balance < amount:
            conn.rollback()
            conn.close()
            await interaction.response.send_message("Not enough currency to trade.", ephemeral=True)
            return
        conn.execute('''
            INSERT INTO currency (user_id, guild_id, character, amount) VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, guild_id, character) DO UPDATE SET amount=excluded.amount
        ''', (sender_id, guild_id, sender_table, sender_balance - amount))
        conn.execute('''
            INSERT INTO currency (user_id, guild_id, character, amount) VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, guild_id, character) DO UPDATE SET amount=amount+excluded.amount
        ''', (recipient_id, guild_id, recipient_table, amount))
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        await interaction.response.send_message(f"Transfer failed: {e}", ephemeral=True)
        return
    conn.close()
    embed = discord.Embed(title=f"{recipient_name} received currency!", color=discord.Color.gold())
    embed.add_field(name="Amount", value=f"{amount:,.2f}", inline=True)
    embed.set_footer(text=f"From {interaction.user.name} ({name})")
    await interaction.response.send_message(f"Gave {amount:,.2f} to {mention} ({recipient_name}).", ephemeral=True)
    await interaction.followup.send(content=f"{mention}", embed=embed, ephemeral=False)

@app_commands.command(name="give_item", description="Give an item to another user.")
@app_commands.describe(
    name="Your character name",
    item="Item to give",
    count="Amount to give",
    mention="Recipient mention",
    recipient_name="Recipient's character name"
)
@app_commands.autocomplete(mention=_mention_autocomplete, item=_item_autocomplete)
async def give_item(interaction: discord.Interaction, name: str, item: str, count: int, mention: str, recipient_name: str):
    sender_id = str(interaction.user.id)
    guild_id = str(interaction.guild.id) if interaction.guild else ''
    sender_table = find_user_db_by_name(USERS_DIR, name, sender_id, guild_id=guild_id)
    if not sender_table:
        await interaction.response.send_message(f'No character found with name {name} for you.', ephemeral=True)
        return
    recipient_id = get_user_id_from_mention(mention)
    recipient_table = find_user_db_by_name(USERS_DIR, recipient_name, recipient_id, guild_id=guild_id)
    if not recipient_table:
        await interaction.response.send_message(f'No character found with name {recipient_name} for {mention}.', ephemeral=True)
        return
    description, icon, _ = fetch_item_details(item, guild_id)
    inv_conn = sqlite3.connect(INVENTORY_DB, timeout=10)
    try:
        inv_conn.execute('BEGIN IMMEDIATE')
        row = inv_conn.execute(
            'SELECT quantity FROM inventory WHERE user_id=? AND guild_id=? AND character=? AND LOWER(item_name)=LOWER(?)',
            (sender_id, guild_id, sender_table, item)
        ).fetchone()
        if not row or row[0] < count:
            inv_conn.rollback()
            inv_conn.close()
            await interaction.response.send_message("Not enough items to trade.", ephemeral=True)
            return
        new_qty = row[0] - count
        if new_qty > 0:
            inv_conn.execute(
                'UPDATE inventory SET quantity=? WHERE user_id=? AND guild_id=? AND character=? AND LOWER(item_name)=LOWER(?)',
                (new_qty, sender_id, guild_id, sender_table, item)
            )
        else:
            inv_conn.execute(
                'DELETE FROM inventory WHERE user_id=? AND guild_id=? AND character=? AND LOWER(item_name)=LOWER(?)',
                (sender_id, guild_id, sender_table, item)
            )
        inv_conn.execute('''
            INSERT INTO inventory (user_id, guild_id, character, item_name, quantity, description, icon)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, guild_id, character, item_name) DO UPDATE SET quantity=quantity+excluded.quantity
        ''', (recipient_id, guild_id, recipient_table, item, count, description, icon))
        inv_conn.commit()
    except Exception as e:
        inv_conn.rollback()
        inv_conn.close()
        await interaction.response.send_message(f"Transfer failed: {e}", ephemeral=True)
        return
    inv_conn.close()
    embed = discord.Embed(title=f"{recipient_name} received {item}!", color=discord.Color.green())
    embed.add_field(name="Item", value=item, inline=True)
    embed.add_field(name="Quantity", value=str(count), inline=True)
    embed.add_field(name="Description", value=description or "No description.", inline=False)
    if icon:
        embed.set_thumbnail(url=icon)
    embed.set_footer(text=f"From {interaction.user.name} ({name})")
    await interaction.response.send_message(f"Gave {count}x {item} to {mention} ({recipient_name}).", ephemeral=True)
    await interaction.followup.send(content=f"{mention}", embed=embed, ephemeral=False)

# ═══════════════════════════════════════════════════════════════════════════════
# Economy Cog — registers all command groups and standalone commands
# ═══════════════════════════════════════════════════════════════════════════════

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        tree = self.bot.tree
        existing_names = {cmd.name for cmd in tree.get_commands()}
        existing_cmd_names = {cmd.name for cmd in tree.get_commands() if isinstance(cmd, app_commands.Command)}

        if currency_group.name not in existing_names:
            tree.add_command(currency_group)
        if work_group.name not in existing_names:
            tree.add_command(work_group)
        if "job" not in existing_cmd_names:
            tree.add_command(job_claim)
        if "give_money" not in existing_cmd_names:
            tree.add_command(give_money)
        if "give_item" not in existing_cmd_names:
            tree.add_command(give_item)


async def setup(bot):
    await bot.add_cog(Economy(bot))

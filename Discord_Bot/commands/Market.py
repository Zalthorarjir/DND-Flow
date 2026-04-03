###################################################################
# Market.py — Item catalog management and Shop                  #
# Merges: Items.py, Shop.py                                     #
###################################################################

import os
import sqlite3
import uuid
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional

from .Inventory import find_user_db_by_name, get_user_id_from_mention, upsert_item, fetch_items
from .Inventory import remove_item as remove_inventory_item
from .Economy import fetch_currency, set_currency

# ─── Constants ────────────────────────────────────────────────────────────────

_BASE         = os.path.dirname(os.path.dirname(__file__))
IMAGES_DIR    = os.path.join(_BASE, 'databases', 'Items')
SHOP_DB_PATH  = os.path.join(_BASE, 'databases', 'Shop.db')
INVENTORY_DB  = os.path.join(_BASE, 'databases', 'Inventory.db')
USERS_DIR     = os.path.join(_BASE, 'databases', 'Users')

os.makedirs(IMAGES_DIR, exist_ok=True)


def _guild_scope_id(guild: Optional[discord.abc.Snowflake]) -> Optional[str]:
    return str(guild.id) if guild and getattr(guild, 'id', None) else None


def _delete_image_if_unreferenced(image_name: Optional[str]):
    normalized = str(image_name or '').strip()
    if not normalized:
        return
    conn = sqlite3.connect(SHOP_DB_PATH)
    try:
        row = conn.execute('SELECT 1 FROM items WHERE image=? LIMIT 1', (normalized,)).fetchone()
    finally:
        conn.close()
    if row:
        return
    image_path = os.path.join(IMAGES_DIR, normalized)
    if os.path.exists(image_path):
        os.remove(image_path)

# ─── Items catalog helpers ────────────────────────────────────────────────────

_CREATE_ITEMS_SQL = '''
CREATE TABLE IF NOT EXISTS items (
    guild_id TEXT NOT NULL,
    name TEXT NOT NULL,
    consumable TEXT NOT NULL CHECK (consumable IN ('Yes', 'No')),
    image TEXT,
    description TEXT,
    PRIMARY KEY (guild_id, name)
);
'''

def _get_items_db():
    conn = sqlite3.connect(SHOP_DB_PATH)
    conn.execute(_CREATE_ITEMS_SQL)
    return conn

def catalog_add_item(guild_id: str, name: str, consumable: str = 'No', image: Optional[str] = None, description: Optional[str] = None):
    conn = _get_items_db()
    try:
        conn.execute(
            'INSERT INTO items (guild_id, name, consumable, image, description) VALUES (?, ?, ?, ?, ?)',
            (guild_id, name, consumable, image, description),
        )
        conn.commit()
    finally:
        conn.close()

def catalog_remove_item(guild_id: str, name: str):
    conn = _get_items_db()
    try:
        cur = conn.execute('SELECT image FROM items WHERE guild_id=? AND name=?', (guild_id, name))
        row = cur.fetchone()
        old_image = row[0] if row and row[0] else None
        conn.execute('DELETE FROM items WHERE guild_id=? AND name=?', (guild_id, name))
        conn.commit()
    finally:
        conn.close()
    _delete_image_if_unreferenced(old_image)

def catalog_set_image(guild_id: str, name: str, image_bytes: bytes, ext: str = 'jpg') -> Optional[str]:
    image_id = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(IMAGES_DIR, exist_ok=True)
    image_path = os.path.join(IMAGES_DIR, image_id)
    with open(image_path, 'wb') as f:
        f.write(image_bytes)
    conn = _get_items_db()
    try:
        row = conn.execute('SELECT image FROM items WHERE guild_id=? AND name=?', (guild_id, name)).fetchone()
        old_image = row[0] if row and row[0] else None
        conn.execute('UPDATE items SET image = ? WHERE guild_id=? AND name = ?', (image_id, guild_id, name))
        conn.commit()
    finally:
        conn.close()
    if old_image and old_image != image_id:
        _delete_image_if_unreferenced(old_image)
    return image_id

def catalog_set_description(guild_id: str, name: str, description: str):
    conn = _get_items_db()
    try:
        conn.execute('UPDATE items SET description = ? WHERE guild_id=? AND name = ?', (description, guild_id, name))
        conn.commit()
    finally:
        conn.close()

def catalog_set_consumable(guild_id: str, name: str, consumable: str):
    if consumable not in ('Yes', 'No'):
        raise ValueError('Consumable must be Yes or No')
    conn = _get_items_db()
    try:
        conn.execute('UPDATE items SET consumable = ? WHERE guild_id=? AND name = ?', (consumable, guild_id, name))
        conn.commit()
    finally:
        conn.close()

def catalog_get_item(guild_id: str, name: str):
    conn = _get_items_db()
    try:
        cur = conn.execute('SELECT name, consumable, image, description FROM items WHERE guild_id=? AND name=?', (guild_id, name))
        return cur.fetchone()
    finally:
        conn.close()

def catalog_list_items(guild_id: str):
    conn = _get_items_db()
    try:
        cur = conn.execute('SELECT name, consumable, image, description FROM items WHERE guild_id=?', (guild_id,))
        return cur.fetchall()
    finally:
        conn.close()

# ─── Shop helpers ─────────────────────────────────────────────────────────────

_CREATE_SHOP_SQL = 'CREATE TABLE IF NOT EXISTS shop (guild_id TEXT NOT NULL, item_name TEXT NOT NULL, price INTEGER NOT NULL, PRIMARY KEY (guild_id, item_name));'

def _get_shop_db():
    conn = sqlite3.connect(SHOP_DB_PATH)
    conn.execute(_CREATE_SHOP_SQL)
    return conn

def get_all_catalog_names(guild_id: str):
    conn = sqlite3.connect(SHOP_DB_PATH)
    try:
        cur = conn.execute('SELECT name FROM items WHERE guild_id=?', (guild_id,))
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()

def get_shop_items(guild_id: str):
    conn = _get_shop_db()
    try:
        return conn.execute('SELECT item_name, price FROM shop WHERE guild_id=?', (guild_id,)).fetchall()
    finally:
        conn.close()

def add_shop_item(guild_id: str, item_name: str, price: int):
    conn = _get_shop_db()
    try:
        conn.execute('INSERT INTO shop (guild_id, item_name, price) VALUES (?, ?, ?)', (guild_id, item_name, price))
        conn.commit()
    finally:
        conn.close()

def remove_shop_item(guild_id: str, item_name: str):
    conn = _get_shop_db()
    try:
        conn.execute('DELETE FROM shop WHERE guild_id=? AND item_name = ?', (guild_id, item_name))
        conn.commit()
    finally:
        conn.close()

def get_shop_item(guild_id: str, item_name: str):
    conn = _get_shop_db()
    try:
        cur = conn.execute('SELECT item_name, price FROM shop WHERE guild_id=? AND item_name = ?', (guild_id, item_name))
        return cur.fetchone()
    finally:
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
# ItemCog — /item commands (admin: manage item catalog)
# ═══════════════════════════════════════════════════════════════════════════════

class ItemCog(commands.GroupCog, name="item"):
    def __init__(self, bot):
        self.bot = bot

    async def _item_name_autocomplete(self, interaction: discord.Interaction, current: str):
        guild_id = _guild_scope_id(interaction.guild)
        names = [name for name, *_ in catalog_list_items(guild_id)] if guild_id else []
        return [app_commands.Choice(name=n, value=n) for n in names if current.lower() in n.lower()][:25]

    @app_commands.command(name="add", description="Add a new item.")
    @app_commands.describe(name="Name of the item")
    async def add(self, interaction: discord.Interaction, name: str):
        if not await _admin_check(interaction):
            return
        try:
            guild_id = _guild_scope_id(interaction.guild)
            catalog_add_item(guild_id, name, consumable="No")
            await interaction.response.send_message(f"Item '{name}' added.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)

    @app_commands.command(name="remove", description="Remove an item and its image from the database.")
    @app_commands.describe(name="Name of the item to remove")
    async def remove(self, interaction: discord.Interaction, name: str):
        if not await _admin_check(interaction):
            return
        try:
            guild_id = _guild_scope_id(interaction.guild)
            conn = sqlite3.connect(SHOP_DB_PATH)
            c = conn.cursor()
            c.execute('SELECT name FROM items WHERE guild_id=? AND LOWER(name) = LOWER(?)', (guild_id, name))
            row = c.fetchone()
            conn.close()
            if not row:
                await interaction.response.send_message(f"Item '{name}' not found in Items.", ephemeral=True)
                return
            canonical_name = row[0]

            # Remove from catalog
            catalog_remove_item(guild_id, canonical_name)

            # Remove from shop
            try:
                conn = sqlite3.connect(SHOP_DB_PATH)
                c = conn.cursor()
                c.execute('DELETE FROM shop WHERE guild_id=? AND LOWER(item_name) = LOWER(?)', (guild_id, canonical_name))
                conn.commit()
                conn.close()
            except Exception:
                pass

            # Remove from all user inventories and refund currency
            def get_shop_price(item_name):
                conn = sqlite3.connect(SHOP_DB_PATH)
                c = conn.cursor()
                c.execute('SELECT price FROM shop WHERE guild_id=? AND LOWER(item_name)=LOWER(?)', (guild_id, item_name))
                row = c.fetchone()
                conn.close()
                return row[0] if row else None

            total_users, total_currency = 0, 0
            shop_price = get_shop_price(canonical_name)
            inv_conn = sqlite3.connect(INVENTORY_DB, timeout=10)
            try:
                inv_conn.execute('BEGIN IMMEDIATE')
                affected = inv_conn.execute(
                    'SELECT user_id, character, quantity FROM inventory WHERE LOWER(item_name)=LOWER(?) AND guild_id=?',
                    (canonical_name, guild_id)
                ).fetchall()
                inv_conn.execute(
                    'DELETE FROM inventory WHERE LOWER(item_name)=LOWER(?) AND guild_id=?',
                    (canonical_name, guild_id)
                )
                inv_conn.commit()
            except Exception:
                inv_conn.rollback()
                inv_conn.close()
                raise
            inv_conn.close()
            for uid, character, qty in affected:
                if shop_price is not None and qty > 0:
                    current = fetch_currency(uid, character, guild_id=guild_id)
                    set_currency(uid, character, current + shop_price * qty, guild_id=guild_id)
                    total_users += 1
                    total_currency += shop_price * qty

            await interaction.response.send_message(
                f"Item '{canonical_name}' removed from Items, Shop, and all user inventories. "
                f"Returned {total_currency:,.2f} currency to {total_users} users (if shop price was set).",
                ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)

    @remove.autocomplete("name")
    async def remove_name_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._item_name_autocomplete(interaction, current)

    # /item set group
    set_group = app_commands.Group(name="set", description="Set item properties.")

    @set_group.command(name="description", description="Set or update the description for an item.")
    @app_commands.describe(name="Name of the item")
    async def set_description(self, interaction: discord.Interaction, name: str):
        if not await _admin_check(interaction):
            return

        class DescriptionModal(discord.ui.Modal, title=f"Set Description for {name}"):
            description = discord.ui.TextInput(
                label="Description", style=discord.TextStyle.paragraph,
                placeholder="Enter the item description...", required=True, max_length=2000
            )
            async def on_submit(self, modal_interaction: discord.Interaction):
                guild_id = _guild_scope_id(modal_interaction.guild)
                catalog_set_description(guild_id, name, self.description.value)
                await modal_interaction.response.send_message(f"Description set for item '{name}'.", ephemeral=True)

        await interaction.response.send_modal(DescriptionModal())

    @set_description.autocomplete("name")
    async def set_description_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._item_name_autocomplete(interaction, current)

    @set_group.command(name="image", description="Set or update the image for an item.")
    @app_commands.describe(name="Name of the item", image="Image attachment")
    async def set_image(self, interaction: discord.Interaction, name: str, image: discord.Attachment):
        if not await _admin_check(interaction):
            return
        if not image.content_type or not image.content_type.startswith("image/"):
            await interaction.response.send_message("Please upload a valid image.", ephemeral=True)
            return
        ext = image.filename.split('.')[-1]
        image_bytes = await image.read()
        try:
            guild_id = _guild_scope_id(interaction.guild)
            image_id = catalog_set_image(guild_id, name, image_bytes, ext)
            await interaction.response.send_message(f"Image set for item '{name}' (ID: {image_id}).", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)

    @set_image.autocomplete("name")
    async def set_image_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._item_name_autocomplete(interaction, current)

    @set_group.command(name="consumable", description="Set whether the item is consumable.")
    @app_commands.describe(name="Name of the item", consumable="Is the item consumable? (Yes/No)")
    @app_commands.choices(consumable=[
        app_commands.Choice(name="Yes", value="Yes"),
        app_commands.Choice(name="No", value="No")
    ])
    async def set_consumable(self, interaction: discord.Interaction, name: str, consumable: app_commands.Choice[str]):
        if not await _admin_check(interaction):
            return
        try:
            guild_id = _guild_scope_id(interaction.guild)
            catalog_set_consumable(guild_id, name, consumable.value)
            await interaction.response.send_message(f"Consumable set to '{consumable.value}' for item '{name}'.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)

    @set_consumable.autocomplete("name")
    async def set_consumable_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._item_name_autocomplete(interaction, current)

    @app_commands.command(name="list", description="List all items.")
    async def list(self, interaction: discord.Interaction):
        if not await _admin_check(interaction):
            return
        guild_id = _guild_scope_id(interaction.guild)
        items = catalog_list_items(guild_id) if guild_id else []
        if not items:
            await interaction.response.send_message("No items found.", ephemeral=True)
            return
        msg = "**Items:**\n"
        for name, consumable, image, description in items:
            msg += f"- **{name}** | Consumable: {consumable} | Image: {image or 'None'} | Description: {description or 'None'}\n"
        await interaction.response.send_message(msg, ephemeral=True)

    @classmethod
    def group_setup(cls):
        cls.set = cls.set_group

ItemCog.group_setup()


# ═══════════════════════════════════════════════════════════════════════════════
# ShopCog — /shop commands (buy, sell, view, add, remove)
# ═══════════════════════════════════════════════════════════════════════════════

class ShopCog(commands.GroupCog, name="shop"):
    def __init__(self, bot):
        self.bot = bot

    async def _catalog_name_autocomplete(self, interaction: discord.Interaction, current: str):
        guild_id = _guild_scope_id(interaction.guild)
        names = get_all_catalog_names(guild_id) if guild_id else []
        return [app_commands.Choice(name=n, value=n) for n in names if current.lower() in n.lower()][:25]

    async def _shop_name_autocomplete(self, interaction: discord.Interaction, current: str):
        guild_id = _guild_scope_id(interaction.guild)
        names = [name for name, _ in get_shop_items(guild_id)] if guild_id else []
        return [app_commands.Choice(name=n, value=n) for n in names if current.lower() in n.lower()][:25]

    @app_commands.command(name="add", description="Add an item to the shop.")
    @app_commands.describe(item="Name of the item", price="Price (whole number)")
    async def add(self, interaction: discord.Interaction, item: str, price: int):
        if not await _admin_check(interaction):
            return
        guild_id = _guild_scope_id(interaction.guild)
        if price < 0:
            await interaction.response.send_message("Price must be a positive whole number.", ephemeral=True)
            return
        if item not in get_all_catalog_names(guild_id):
            await interaction.response.send_message(f"Item '{item}' does not exist in Items. Add it through /item first.", ephemeral=True)
            return
        if get_shop_item(guild_id, item):
            await interaction.response.send_message(f"Item '{item}' is already in the shop.", ephemeral=True)
            return
        add_shop_item(guild_id, item, price)
        await interaction.response.send_message(f"Added '{item}' to the shop for {price}.", ephemeral=True)

    @add.autocomplete("item")
    async def add_item_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._catalog_name_autocomplete(interaction, current)

    @app_commands.command(name="remove", description="Remove an item from the shop.")
    @app_commands.describe(item="Name of the item to remove")
    async def remove(self, interaction: discord.Interaction, item: str):
        if not await _admin_check(interaction):
            return
        guild_id = _guild_scope_id(interaction.guild)
        if not get_shop_item(guild_id, item):
            await interaction.response.send_message(f"Item '{item}' does not exist in the shop.", ephemeral=True)
            return
        remove_shop_item(guild_id, item)
        await interaction.response.send_message(f"Removed '{item}' from the shop.", ephemeral=True)

    @remove.autocomplete("item")
    async def remove_item_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._shop_name_autocomplete(interaction, current)

    @app_commands.command(name="view", description="View the shop.")
    async def view(self, interaction: discord.Interaction):
        guild_id = _guild_scope_id(interaction.guild)
        items = get_shop_items(guild_id) if guild_id else []
        if not items:
            await interaction.response.send_message("No items in the shop.", ephemeral=True)
            return
        per_page = 10
        total_pages = (len(items) - 1) // per_page + 1

        def get_page_embed(page_idx):
            embed = discord.Embed(title="Shop", description=f"Page {page_idx+1}/{total_pages}", color=discord.Color.gold())
            start = page_idx * per_page
            for i, (name, price) in enumerate(items[start:min(start + per_page, len(items))], start=1):
                embed.add_field(name=f"{i+start}. {name}", value=f"Price: {price}", inline=False)
            embed.set_footer(text="Shop")
            return embed

        class ShopView(discord.ui.View):
            def __init__(self, items, page=0):
                super().__init__(timeout=180)
                self.items = items
                self.page = page
                self.total_pages = (len(items) - 1) // per_page + 1
                self.add_item(self.make_dropdown())
                if self.total_pages > 1:
                    self.add_item(self.PrevButton(self))
                    self.add_item(self.NextButton(self))

            def make_dropdown(self):
                start = self.page * per_page
                end = min(start + per_page, len(self.items))
                options = [
                    discord.SelectOption(label=name[:100], description=f"Price: {price}", value=str(idx+start))
                    for idx, (name, price) in enumerate(self.items[start:end])
                ]
                return self.ItemDropdown(options, self)

            class ItemDropdown(discord.ui.Select):
                def __init__(self, options, parent_view):
                    super().__init__(placeholder="Select an item to view", options=options, custom_id="item_select")
                    self.parent_view = parent_view

                async def callback(self, interaction: discord.Interaction):
                    idx = int(self.values[0])
                    name, price = self.parent_view.items[idx]
                    guild_id = _guild_scope_id(interaction.guild)
                    conn = sqlite3.connect(SHOP_DB_PATH)
                    c = conn.cursor()
                    c.execute('SELECT description, image, consumable FROM items WHERE guild_id=? AND name=?', (guild_id, name))
                    row = c.fetchone()
                    conn.close()
                    desc = row[0] if row else ''
                    image = row[1] if row else ''
                    consumable = row[2] if row else ''
                    embed = discord.Embed(title=f"{name}", color=discord.Color.green())
                    embed.add_field(name="Price", value=f"{price}", inline=False)
                    embed.add_field(name="Description", value=desc or "No description.", inline=False)
                    embed.add_field(name="Consumable", value=consumable or "No", inline=False)
                    file = None
                    if image:
                        if not image.startswith('http'):
                            image_path = os.path.join(IMAGES_DIR, image)
                            if os.path.exists(image_path):
                                file = discord.File(image_path, filename=image)
                                embed.set_thumbnail(url=f"attachment://{image}")
                            else:
                                embed.set_thumbnail(url=image)
                        else:
                            embed.set_thumbnail(url=image)
                    embed.set_footer(text="Shop")
                    if file:
                        await interaction.response.send_message(embed=embed, file=file, ephemeral=True)
                    else:
                        await interaction.response.send_message(embed=embed, ephemeral=True)

            class PrevButton(discord.ui.Button):
                def __init__(self, parent_view):
                    super().__init__(style=discord.ButtonStyle.primary, label="Previous", custom_id="prev_page")
                    self.parent_view = parent_view
                async def callback(self, interaction: discord.Interaction):
                    if self.parent_view.page > 0:
                        self.parent_view.page -= 1
                        await interaction.response.edit_message(embed=get_page_embed(self.parent_view.page), view=ShopView(self.parent_view.items, self.parent_view.page))

            class NextButton(discord.ui.Button):
                def __init__(self, parent_view):
                    super().__init__(style=discord.ButtonStyle.primary, label="Next", custom_id="next_page")
                    self.parent_view = parent_view
                async def callback(self, interaction: discord.Interaction):
                    if self.parent_view.page < self.parent_view.total_pages - 1:
                        self.parent_view.page += 1
                        await interaction.response.edit_message(embed=get_page_embed(self.parent_view.page), view=ShopView(self.parent_view.items, self.parent_view.page))

        await interaction.response.send_message(embed=get_page_embed(0), view=ShopView(items, 0), ephemeral=True)

    @app_commands.command(name="buy", description="Buy an item from the shop.")
    @app_commands.describe(item="Name of the item", amount="Amount to buy", name="Character/Inventory name (optional)")
    async def buy(self, interaction: discord.Interaction, item: str, amount: int, name: Optional[str] = None):
        user_id = str(interaction.user.id)
        guild_id = _guild_scope_id(interaction.guild)
        shop_entry = get_shop_item(guild_id, item)
        if not shop_entry:
            await interaction.response.send_message(f"Item '{item}' is not in the shop.", ephemeral=True)
            return
        price = shop_entry[1]
        if name:
            table_name = find_user_db_by_name(USERS_DIR, name, user_id, guild_id=guild_id)
            if not table_name:
                await interaction.response.send_message(f'No character found with name {name}.', ephemeral=True)
                return
            table = table_name
        else:
            table = 'Currency'
        current = fetch_currency(user_id, table, guild_id=guild_id)
        total_cost = price * amount
        if current < total_cost:
            await interaction.response.send_message(f"Not enough currency. You need {total_cost:,.2f}, but have {current:,.2f}.", ephemeral=True)
            return
        set_currency(user_id, table, current - total_cost, guild_id=guild_id)
        inv_table = table if name else 'Inventory'
        upsert_item(user_id, inv_table, item, amount, guild_id=guild_id)
        await interaction.response.send_message(f"Bought {amount}x {item} for {total_cost:,.2f}.", ephemeral=True)

    @buy.autocomplete("item")
    async def buy_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._shop_name_autocomplete(interaction, current)

    @app_commands.command(name="sell", description="Sell an item to the shop.")
    @app_commands.describe(item="Name of the item", amount="Amount to sell", name="Character/Inventory name (optional)")
    async def sell(self, interaction: discord.Interaction, item: str, amount: int, name: Optional[str] = None):
        user_id = str(interaction.user.id)
        guild_id = _guild_scope_id(interaction.guild)
        shop_entry = get_shop_item(guild_id, item)
        if not shop_entry:
            await interaction.response.send_message(f"Item '{item}' is not in the shop.", ephemeral=True)
            return
        price = shop_entry[1]
        if name:
            table_name = find_user_db_by_name(USERS_DIR, name, user_id, guild_id=guild_id)
            if not table_name:
                await interaction.response.send_message(f'No character found with name {name}.', ephemeral=True)
                return
            table = table_name
        else:
            table = 'Inventory'
        items = fetch_items(user_id, table, guild_id=guild_id)
        item_row = next((r for r in items if r[0].lower() == item.lower()), None)
        if not item_row or item_row[1] < amount:
            await interaction.response.send_message(f"Not enough '{item}' to sell.", ephemeral=True)
            return
        remove_inventory_item(user_id, table, item, amount, guild_id=guild_id)
        cur_balance = fetch_currency(user_id, table, guild_id=guild_id)
        set_currency(user_id, table, cur_balance + price * amount, guild_id=guild_id)
        await interaction.response.send_message(f"Sold {amount}x {item} for {price * amount:,.2f}.", ephemeral=True)

    @sell.autocomplete("item")
    async def sell_autocomplete(self, interaction: discord.Interaction, current: str):
        return await self._shop_name_autocomplete(interaction, current)


# ─── Extension setup ──────────────────────────────────────────────────────────

async def setup(bot):
    await bot.add_cog(ItemCog(bot))
    await bot.add_cog(ShopCog(bot))

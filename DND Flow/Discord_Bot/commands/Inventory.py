def debug_print_user_db(users_folder, user_id):
	db_path = os.path.join(users_folder, f"{user_id}.db")
	if not os.path.exists(db_path):
		print(f"[DEBUG] User DB file does not exist: {db_path}")
		return
	print(f"[DEBUG] Printing all tables and contents for: {db_path}")
	conn = sqlite3.connect(db_path)
	c = conn.cursor()
	try:
		c.execute('SELECT Name FROM sqlite_master WHERE type="table"')
		tables = [row[0] for row in c.fetchall()]
		print(f"[DEBUG] Tables found: {tables}")
		for t in tables:
			print(f"[DEBUG] Table: {t}")
			c.execute(f'PRAGMA table_info([{t}])')
			columns = [row[1] for row in c.fetchall()]
			print(f"[DEBUG] Columns: {columns}")
			c.execute(f'SELECT * FROM [{t}]')
			rows = c.fetchall()
			for row in rows:
				print(f"[DEBUG] Row: {row}")
	except Exception as e:
		print(f"[DEBUG] Exception while printing user DB: {e}")
	finally:
		conn.close()



import discord
from discord.ext import commands
from discord import app_commands
import os
import sqlite3
from math import ceil
from typing import Optional

# Import Config Cog for admin check
from .Config import Config

import re as _re

_BASE_DIR    = os.path.dirname(os.path.dirname(__file__))
_SHOP_DB     = os.path.join(_BASE_DIR, 'databases', 'Shop.db')
INVENTORY_DB = os.path.join(_BASE_DIR, 'databases', 'Inventory.db')

def get_user_id_from_mention(mention):
	m = _re.match(r'^<@!?(\d+)>$', str(mention).strip())
	return m.group(1) if m else None

def find_user_db_by_name(users_folder, name, user_id=None, guild_id=None):
	"""
	Validate that a character named `name` exists for `user_id` in Sheets.db.
	Returns `name` (used as the table name in per-user Item/Currency DBs) if found,
	otherwise returns None.

	guild_id: restrict to a specific guild when provided; searches all guilds when None.
	"""
	if not user_id or not name:
		return None
	from .sheet_storage import connect_db as _sheets_connect
	conn = _sheets_connect()
	try:
		if guild_id:
			row = conn.execute(
				"SELECT 1 FROM characters WHERE user_id=? AND guild_id=? AND name=? COLLATE NOCASE",
				(str(user_id), str(guild_id), name),
			).fetchone()
		else:
			row = conn.execute(
				"SELECT 1 FROM characters WHERE user_id=? AND name=? COLLATE NOCASE",
				(str(user_id), name),
			).fetchone()
		return name if row else None
	finally:
		conn.close()

def _ensure_guild_id_column():
	"""Add guild_id column and unique index to inventory table if missing (one-time migration)."""
	conn = sqlite3.connect(INVENTORY_DB)
	try:
		cols = {row[1] for row in conn.execute('PRAGMA table_info(inventory)').fetchall()}
		if 'guild_id' not in cols:
			conn.execute('ALTER TABLE inventory ADD COLUMN guild_id TEXT NOT NULL DEFAULT ""')
			conn.commit()
		# Create a unique index so ON CONFLICT(user_id, guild_id, character, item_name) works
		# on databases originally created without guild_id in the PRIMARY KEY.
		indexes = {row[1] for row in conn.execute("PRAGMA index_list(inventory)").fetchall()}
		if 'inventory_guild_scope_uidx' not in indexes:
			conn.execute(
				'CREATE UNIQUE INDEX IF NOT EXISTS inventory_guild_scope_uidx '
				'ON inventory (user_id, guild_id, character, item_name)'
			)
			conn.commit()
	finally:
		conn.close()


def upsert_item(user_id, character, item_name, quantity, description='', icon='', guild_id=''):
	_ensure_guild_id_column()
	conn = sqlite3.connect(INVENTORY_DB)
	conn.execute('''
		INSERT INTO inventory (user_id, guild_id, character, item_name, quantity, description, icon)
		VALUES (?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(user_id, guild_id, character, item_name) DO UPDATE SET quantity=quantity+excluded.quantity
	''', (str(user_id), str(guild_id), character, item_name, quantity, description, icon))
	conn.commit()
	conn.close()

def remove_item(user_id, character, item_name, quantity, guild_id=''):
	_ensure_guild_id_column()
	conn = sqlite3.connect(INVENTORY_DB)
	c = conn.cursor()
	c.execute('SELECT quantity FROM inventory WHERE user_id=? AND guild_id=? AND character=? AND LOWER(item_name)=LOWER(?)',
	          (str(user_id), str(guild_id), character, item_name))
	row = c.fetchone()
	if row:
		new_qty = row[0] - quantity
		if new_qty > 0:
			c.execute('UPDATE inventory SET quantity=? WHERE user_id=? AND guild_id=? AND character=? AND LOWER(item_name)=LOWER(?)',
			          (new_qty, str(user_id), str(guild_id), character, item_name))
		else:
			c.execute('DELETE FROM inventory WHERE user_id=? AND guild_id=? AND character=? AND LOWER(item_name)=LOWER(?)',
			          (str(user_id), str(guild_id), character, item_name))
		conn.commit()
	conn.close()


def fetch_items(user_id, character, guild_id=''):
	_ensure_guild_id_column()
	conn = sqlite3.connect(INVENTORY_DB)
	c = conn.cursor()
	c.execute('SELECT item_name, quantity FROM inventory WHERE user_id=? AND guild_id=? AND character=?',
	          (str(user_id), str(guild_id), character))
	items = c.fetchall()
	conn.close()
	return items

def fetch_item_details(item_name, guild_id=None):
	conn = sqlite3.connect(_SHOP_DB)
	c = conn.cursor()
	try:
		if guild_id:
			c.execute('SELECT description, image, consumable FROM items WHERE guild_id=? AND name=?', (str(guild_id), item_name))
		else:
			c.execute('SELECT description, image, consumable FROM items WHERE name=?', (item_name,))
		row = c.fetchone()
		if row:
			desc = row[0] or ''
			image = row[1] or ''
			consumable = row[2] if len(row) > 2 else None
			return desc, image, consumable
		else:
			return '', '', None
	except Exception as e:
		print(f"[DEBUG] Exception fetching item details for {item_name}: {e}")
		return '', '', None
	finally:
		conn.close()


# --- SLASH COMMAND GROUP AND SUBCOMMANDS DEFINED AT MODULE LEVEL ---
inventory_group = app_commands.Group(name="inventory", description="Inventory commands")



@inventory_group.command(name="add", description="Add an item to a user's inventory or custom table.")
async def add(interaction: discord.Interaction,
			  mention: str,
			  item_name: str,
			  quantity: int,
			  name: Optional[str] = None):
	# Admin check using Config Cog
	from discord.ext import commands as ext_commands
	bot = interaction.client
	if not isinstance(bot, ext_commands.Bot):
		await interaction.response.send_message("Bot instance not found.", ephemeral=True)
		return
	config_cog = bot.get_cog("Config")
	is_admin = getattr(config_cog, "is_admin", None)
	if not config_cog or not is_admin or not (await is_admin(interaction)):
		await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
		return
	users_folder = os.path.join(os.path.dirname(__file__), '..', 'databases', 'Users')
	user_id = get_user_id_from_mention(mention)
	guild_id = str(interaction.guild_id or '')
	print(f"[DEBUG] /inventory add called with mention={mention}, item_name={item_name}, quantity={quantity}, name={name}")
	if name:
		table_name = find_user_db_by_name(users_folder, name, user_id, guild_id=guild_id)
		print(f"[DEBUG] find_user_db_by_name returned table_name={table_name}")
		if not table_name:
			await interaction.response.send_message(f'No character found with name {name}.', ephemeral=True)
			return
		print(f"[DEBUG] add: user_id={user_id}, guild_id={guild_id}, table={table_name}")
		upsert_item(user_id, table_name, item_name, quantity, guild_id=guild_id)
		await interaction.response.send_message(f'Added {quantity}x {item_name} to {name} for <@{user_id}>.')
	else:
		print(f"[DEBUG] add: user_id={user_id}, guild_id={guild_id}, table=Inventory")
		upsert_item(user_id, 'Inventory', item_name, quantity, guild_id=guild_id)
		await interaction.response.send_message(f'Added {quantity}x {item_name} to Inventory for <@{user_id}>.')



@inventory_group.command(name="view", description="View a user's inventory or custom table.")
async def view(interaction: discord.Interaction,
			  mention: str,
			  name: Optional[str] = None):
	users_folder = os.path.join(os.path.dirname(__file__), '..', 'databases', 'Users')
	user_id = get_user_id_from_mention(mention)
	if not user_id:
		await interaction.response.send_message('Invalid user mention.', ephemeral=True)
		return
	guild_id = str(interaction.guild_id or '')
	print(f"[DEBUG] /inventory view called with mention={mention}, name={name}")
	try:
		username = (await interaction.client.fetch_user(int(user_id))).name
	except Exception:
		username = str(user_id)
	if name:
		table_name = find_user_db_by_name(users_folder, name, user_id, guild_id=guild_id)
		print(f"[DEBUG] find_user_db_by_name returned table_name={table_name}")
		if not table_name:
			await interaction.response.send_message(f'No character found with name {name}.', ephemeral=True)
			return
		table = table_name
		footer = f'{username} + {name}'
		print(f"[DEBUG] view: user_id={user_id}, guild_id={guild_id}, table={table}")
	else:
		table = 'Inventory'
		footer = username
		print(f"[DEBUG] view: user_id={user_id}, guild_id={guild_id}, table=Inventory")
	items = fetch_items(user_id, table, guild_id=guild_id)
	print(f"[DEBUG] view: fetched items: {items}")
	if not items:
		await interaction.response.send_message('No items found.', ephemeral=True)
		return
	per_page = 10
	total_pages = (len(items) - 1) // per_page + 1

	def get_page_embed(page_idx):
		embed = discord.Embed(title=f"Inventory for {footer}", description=f"Page {page_idx+1}/{total_pages}", color=discord.Color.blue())
		start = page_idx * per_page
		end = min(start + per_page, len(items))
		for i, (name_, qty) in enumerate(items[start:end], start=1):
			embed.add_field(name=f"{i+start}. {name_}", value=f"Qty: {qty}", inline=False)
		embed.set_footer(text=footer)
		return embed

	def get_page_dropdown(page_idx):
		start = page_idx * per_page
		end = min(start + per_page, len(items))
		options = []
		for idx, (name_, qty) in enumerate(items[start:end]):
			options.append(
				discord.SelectOption(label=name_[:100], description=f"Qty: {qty}", value=str(idx+start))
			)
		return discord.ui.Select(placeholder="Select an item to view", options=options, custom_id="item_select")

	class InventoryView(discord.ui.View):
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
			options = []
			for idx, (name_, qty) in enumerate(self.items[start:end]):
				options.append(
					discord.SelectOption(label=name_[:100], description=f"Qty: {qty}", value=str(idx+start))
				)
			dropdown = self.ItemDropdown(options, self)
			return dropdown

		class ItemDropdown(discord.ui.Select):
			def __init__(self, options, parent_view):
				super().__init__(placeholder="Select an item to view", options=options, custom_id="item_select")
				self.parent_view = parent_view

			async def callback(self, interaction: discord.Interaction):
				idx = int(self.values[0])
				name_, qty = self.parent_view.items[idx]
				desc, icon, consumable = fetch_item_details(name_, str(interaction.guild.id) if interaction.guild else None)
				embed = discord.Embed(title=f"{name_}", color=discord.Color.green())
				embed.add_field(name="Quantity", value=f"{qty}", inline=False)
				embed.add_field(name="Description", value=desc or "No description.", inline=False)
				file = None
				if icon:
					if not icon.startswith('http'):
						icon_path = os.path.join(os.path.dirname(__file__), '..', 'databases', 'Items', icon)
						if os.path.exists(icon_path):
							file = discord.File(icon_path, filename=icon)
							embed.set_thumbnail(url=f"attachment://{icon}")
						else:
							embed.set_thumbnail(url=icon)
					else:
						embed.set_thumbnail(url=icon)
				embed.set_footer(text=footer)

				class ConsumeButton(discord.ui.Button):
					def __init__(self, parent_view, item_name, table, user_id, guild_id):
						super().__init__(style=discord.ButtonStyle.danger, label="Consume", custom_id="consume_btn")
						self.parent_view = parent_view
						self.item_name = item_name
						self.table = table
						self.user_id = user_id
						self.guild_id = guild_id

					async def callback(self, interaction: discord.Interaction):
						# Remove 1 from inventory
						remove_item(self.user_id, self.table, self.item_name, 1, guild_id=self.guild_id)
						# Fetch new quantity
						items = fetch_items(self.user_id, self.table, guild_id=self.guild_id)
						new_qty = 0
						for n, q in items:
							if n == self.item_name:
								new_qty = q
								break
						desc, icon, _ = fetch_item_details(self.item_name, str(interaction.guild.id) if interaction.guild else None)
						embed = discord.Embed(title=f"{self.item_name}", color=discord.Color.green())
						embed.add_field(name="Quantity", value=f"{new_qty}", inline=False)
						embed.add_field(name="Description", value=desc or "No description.", inline=False)
						file = None
						if icon:
							if not icon.startswith('http'):
								icon_path = os.path.join(os.path.dirname(__file__), '..', 'databases', 'Items', icon)
								if os.path.exists(icon_path):
									file = discord.File(icon_path, filename=icon)
									embed.set_thumbnail(url=f"attachment://{icon}")
								else:
									embed.set_thumbnail(url=icon)
							else:
								embed.set_thumbnail(url=icon)
						embed.set_footer(text=footer)
						if new_qty > 0:
							if file:
								await interaction.response.edit_message(embed=embed, attachments=[file], view=self.parent_view)
							else:
								await interaction.response.edit_message(embed=embed, view=self.parent_view)
						else:
							await interaction.response.edit_message(content=f"You have consumed your last {self.item_name}.", embed=None, attachments=[], view=None)

				view = discord.ui.View()
				if consumable and str(consumable).lower() in ("yes", "true", "1"):  # Marked as consumable
					# Pass table and user_id for removal
					view.add_item(ConsumeButton(self.parent_view, name_, table, user_id, guild_id))
				# Always pass a View (even if empty), since None is not allowed for the view parameter
				if file:
					await interaction.response.send_message(embed=embed, file=file, ephemeral=True, view=view)
				else:
					await interaction.response.send_message(embed=embed, ephemeral=True, view=view)

		class PrevButton(discord.ui.Button):
			def __init__(self, parent_view):
				super().__init__(style=discord.ButtonStyle.primary, label="Previous", custom_id="prev_page")
				self.parent_view = parent_view
			async def callback(self, interaction: discord.Interaction):
				if self.parent_view.page > 0:
					self.parent_view.page -= 1
					await interaction.response.edit_message(embed=get_page_embed(self.parent_view.page), view=InventoryView(self.parent_view.items, self.parent_view.page))

		class NextButton(discord.ui.Button):
			def __init__(self, parent_view):
				super().__init__(style=discord.ButtonStyle.primary, label="Next", custom_id="next_page")
				self.parent_view = parent_view
			async def callback(self, interaction: discord.Interaction):
				if self.parent_view.page < self.parent_view.total_pages - 1:
					self.parent_view.page += 1
					await interaction.response.edit_message(embed=get_page_embed(self.parent_view.page), view=InventoryView(self.parent_view.items, self.parent_view.page))

	await interaction.response.send_message(embed=get_page_embed(0), view=InventoryView(items, 0), ephemeral=True)



@inventory_group.command(name="remove", description="Remove an item from a user's inventory or custom table.")
async def remove(interaction: discord.Interaction,
				mention: str,
				item_name: str,
				quantity: int,
				name: Optional[str] = None):
	# Admin check using Config Cog
	from discord.ext import commands as ext_commands
	bot = interaction.client
	if not isinstance(bot, ext_commands.Bot):
		await interaction.response.send_message("Bot instance not found.", ephemeral=True)
		return
	config_cog = bot.get_cog("Config")
	is_admin = getattr(config_cog, "is_admin", None)
	if not config_cog or not is_admin or not (await is_admin(interaction)):
		await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
		return
	users_folder = os.path.join(os.path.dirname(__file__), '..', 'databases', 'Users')
	user_id = get_user_id_from_mention(mention)
	if not user_id:
		await interaction.response.send_message('Invalid user mention.', ephemeral=True)
		return
	guild_id = str(interaction.guild_id or '')
	print(f"[DEBUG] /inventory remove called with mention={mention}, item_name={item_name}, quantity={quantity}, name={name}")
	if name:
		table_name = find_user_db_by_name(users_folder, name, user_id, guild_id=guild_id)
		print(f"[DEBUG] find_user_db_by_name returned table_name={table_name}")
		if not table_name:
			await interaction.response.send_message(f'No character found with name {name}.', ephemeral=True)
			return
		print(f"[DEBUG] remove: user_id={user_id}, guild_id={guild_id}, table={table_name}")
		remove_item(user_id, table_name, item_name, quantity, guild_id=guild_id)
		await interaction.response.send_message(f'Removed {quantity}x {item_name} from {name} for <@{user_id}>.')
	else:
		print(f"[DEBUG] remove: user_id={user_id}, guild_id={guild_id}, table=Inventory")
		remove_item(user_id, 'Inventory', item_name, quantity, guild_id=guild_id)
		await interaction.response.send_message(f'Removed {quantity}x {item_name} from Inventory for <@{user_id}>.')

class Inventory(commands.Cog):
	def __init__(self, bot):
		self.bot = bot

	async def cog_load(self):
		# Only add if not already present
		if not any(cmd.name == inventory_group.name for cmd in self.bot.tree.get_commands()):
			self.bot.tree.add_command(inventory_group)

async def setup(bot):
	await bot.add_cog(Inventory(bot))

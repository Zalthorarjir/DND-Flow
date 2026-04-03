import discord
from discord.ext import commands
from discord import app_commands
import inspect

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show help for all commands, grouped by category.")
    async def help_command(self, interaction: discord.Interaction):
        # Manual command group and command descriptions for DND Flow
        command_groups = [
            {
                "name": "Work",
                "description": "Job and work-related commands.",
                "commands": [
                    {"name": "/work create <job> <payment>", "desc": "Create a new job with a payment amount.\n``<job>``: Job name\n``<payment>``: Wage per cooldown cycle."},
                    {"name": "/work edit <job> <payment>", "desc": "Edit an existing job's payment amount.\n``<job>``: Job name\n``<payment>``: New wage."},
                    {"name": "/work assign <job> <mention> <name>", "desc": "Assign a job to a user's character.\n``<job>``: Job name\n``<mention>``: User mention\n``<name>``: Character name."},
                    {"name": "/job <name>", "desc": "Claim your job payout for a character.\n``<name>``: Character name."},
                ]
            },
            {
                "name": "Inventory",
                "description": "Manage user inventories and items.",
                "commands": [
                    {"name": "/inventory add <mention> <item_name> <quantity> (name)", "desc": "Add an item to a user's inventory or character.\n``<mention>``: User mention\n``<item_name>``: Item,\n``<quantity>``: Amount,\n``(name)``: Character name (optional if no Character name is given, it will go to the user's inventory.)."},
                    {"name": "/inventory view <mention> (name)", "desc": "View a your inventory or character's inventory.\n``<mention>``: User mention\n``(name)``: Character name (optional if no Character name is given, it will look in the your inventory.)."},
                    {"name": "/inventory remove <mention> <item_name> <quantity> (name)", "desc": "Remove an item from a user's inventory or custom table.\n``<mention>``: User mention,\n``<item_name>``: Item,\n``<quantity>``: Amount,\n``(name)``: Character name (optional if no Character name is given, it will go to take from user's inventory.)."},
                ]
            },
            {
                "name": "Items",
                "description": "Manage item definitions and properties.",
                "commands": [
                    {"name": "/item add <name> <consumable> (image) (description)", "desc": "Add a new item.\n``<name>``: Item name,\n``<consumable>``: Yes/No,\n``(image)``: Image file,\n``(description)``: Description."},
                    {"name": "/item set consumable <name> <Yes/No>", "desc": "Set an item's consumable status.\n``<name>``: Item name\n``<Yes/No>``: Simply Yes or No."},
                    {"name": "/item set_description <name>", "desc": "Set or update the description for an item.\n``<name>``: Item name\nA new window will pop up to write the description."},
                    {"name": "/item set_image <name> <image>", "desc": "Set or update the image for an item.\n``<name>``: Item name\n``<image>``: Image file."},
                    {"name": "/item list <name>", "desc": "Lists all items."},
                    {"name": "/item remove <name>", "desc": "Remove an item by name.\n``<name>``: Item name."},
                ]
            },
            {
                "name": "Shop",
                "description": "Shop and trading commands.",
                "commands": [
                    {"name": "/shop add <item> <price>", "desc": "Add an item to the shop. <item>: Item name, <price>: Price."},
                    {"name": "/shop remove <item>", "desc": "Remove an item from the shop.\n``<item>``: Item name."},
                    {"name": "/shop view", "desc": "List all items available in the shop."},
                    {"name": "/shop buy <item> <quantity> (name)", "desc": "Buy an item from the shop.\n``<item>``: Item name\n``<quantity>``: Amount.\n``(name)``: Your character name, if not giving charactername it will buy for your inventory."},
                    {"name": "/shop sell <item> <quantity> (name)", "desc": "Sell an item to the shop.\n``<item>``: Item name\n``<quantity>``: Amount.\n``(name)``: Your character name, if not giving charactername it will sell from your inventory."},
                ]
            },
            {
                "name": "Trade",
                "description": "Trade items and currency between users.",
                "commands": [
                    {"name": "/give_item <name> <item> <count> <mention> <recipient_name>", "desc": "Give an item to another user or character.\n``<name>``: Your character,\n``<item>``: Item,\n``<count>``: Amount,\n``<mention>``: Recipient,\n``<recipient_name>``: Recipient's character."},
                    {"name": "/give_money <name> <amount> <mention> <recipient_name>", "desc": "Give currency to another user or character.\n``<name>``: Your character,\n``<amount>``: Amount,\n``<mention>``: Recipient,\n``<recipient_name>``: Recipient's character."},
                ]
            },
            {
                "name": "Sheet",
                "description": "Character sheet and field management.",
                "commands": [
                    {"name": "/sheet new <name>", "desc": "Create a new character sheet.\n``<name>``: Character name."},
                    {"name": "/sheet drafts", "desc": "View all character drafts (Sheets that do not have approved status, it will also show the sheet IDs.)"},
                    {"name": "/sheet edit <sheetid> <field name>", "desc": "Edit a field on a character sheet.\n``<sheetid>``: Sheet ID,\n``<field name>``: Field name,\n A new window will pop up to write in the field."},
                    {"name": "/sheet icon <sheetid>", "desc": "Add a image to your character. (Only one image per character)\n``<sheetid>``: Sheet ID."},
                    {"name": "/sheet list", "desc": "View all character sheets."},
                    {"name": "/sheet remove <name>", "desc": "Remove a character sheet.\n``<name>``: Character name."},
                ]
            },
            {
                "name": "Currency",
                "description": "Manage user and character currency.",
                "commands": [
                    {"name": "/currency view <mention> (name)", "desc": "View a user's currency amount.\n``<mention>``: User mention,\n``(name)``: Character name (optional shows the amount for the Character.)"},
                    {"name": "/currency set <mention> <amount> (name)", "desc": "Set a user's currency amount.\n``<mention>``: User mention,\n``<amount>``: Amount,\n``(name)``: Character name (optional if not specified currency will be added to the user inventory.)"},
                    {"name": "/currency remove <mention> <amount> (name)", "desc": "Remove an amount from a user's currency.\n``<mention>``: User mention,\n``<amount>``: Amount,\n``(name)``: Character name (optional if not specified currency will be removed from the user inventory.)."},
                ]
            },
            {
                "name": "Config",
                "description": "Bot configuration and admin commands.",
                "commands": [
                    {"name": "/config field add <fieldname>", "desc": "Create another field for sheets.\n``<field>``: Name of the field to add."},
                    {"name": "/config field remove <fieldname>", "desc": "Remove a configuration field.\n``<field>``: Name of the field to remove."},
                    {"name": "/config channel <Channeltype> <channel>", "desc": "Set a configuration channel.\n``<Channeltype>``: Type of the channel\n``<channel>``: Channel.\n''Admin'': where Sheet submissions are send.\n''Member'':When sheets are Approved/Denied/Dissussion Marked are send here."},
                    {"name": "/config role <Roletype> <role>", "desc": "Set a configuration role.\n``<Roletype>``: Type of the role.\n``<role>``: Role.''Admin'': Admin Permission Role.\n''Member'': Member Permission Role."},
                ]
            },
            {
                "name": "Death",
                "description": "Death and revival commands.",
                "commands": [
                    {"name": "/death reset <mention> <name>", "desc": "Reset a character's death status.\n``<mention>``: User mention,\n``<name>``: Character name."},
                    {"name": "/death infinite <Yes/No>", "desc": "Set a death to permanent or cooldown.\n``<Yes/No>``: Yes for Permanent, No for Cooldown."},
                    {"name": "/death set <time>", "desc": "Set death cooldown in days.\n``<time>``: Time in days."},
                    {"name": "/check <name>", "desc": "Check you character's death cooldown status.\n``<name>``: Character name."},
                    {"name": "/Death claim <mention> <name>", "desc": "Claim a character's death status.\n``<mention>``: User mention,\n``<name>``: Character name.\n After Admin descision you both recieve a reply in the same channel as the command was send."},
                    {"name": "/death list", "desc": "List all your characters currently reported as dead."},
                    {"name": "/death graveyard", "desc": "List all characters currenly reported as dead."},
                    {"name": "/death check <name>", "desc": "Check your own character's death status and cooldown.\n``<name>``: Character name."},
                    {"name": "/death revive <name>", "desc": "Revive a dead character if the cooldown is over.\n``<name>``: Character name."},
                ]
            },
            {
                "name": "Combat",
                "description": "Healthtracker and Dynamic Combat Commands.",
                "commands": [
                    {"name": "/health_track <name> <hp>", "desc": "Track your character's health.\n``<name>``: Your Character's name,\n``<hp>``: Amount of health points."},
                    {"name": "/fight-dynamic dynamic <oc>: <opponent>: <opponentoc>:", "desc": "Track your character's health.\n``<oc>``: Your Character's name,\n``<opponent>``: User mention,\n``<opponentoc>``: Opponent's character name."},
                    {"name": "/fight-dynamic rules <solid_hit>: <small_hit>: <missed>: <self_hit>:", "desc": "``<solid_hit>``: Chance for solid hit (-2 HP)\n``<small_hit>``: Chance for small hit (-1 HP)\n``<missed>``: Chance for missed hit (0 HP),\n``<self_hit>``: Chance for self-inflicted hit causing (-1 HP) to the attacker.\nDefine ``0`` for disabled.\n Use ``0.1`` up to ``1`` for the chance percentage scaling. (1 Will be highest chance.)"},
                ]
            },
            {
                "name": "Search",
                "description": "Search for items, characters, or users.",
                "commands": [
                    {"name": "/search", "desc": "Choose between ``<Mention>`` or ``<Name>``\n Or use both to search more specifically.\n***Will only show characters who have Approved status.**"},
                ]
            },
            {
                "name": "Help",
                "description": "Show this help message.",
                "commands": [
                    {"name": "/help", "desc": "Show help for all commands, grouped by category.\n``` ```"},
                    {"name": "If you need further assistance", "desc": "Contact your project maintainer or deployment owner for support.\n\nIf you fork or redistribute the bot, keep your own support details up to date in this help entry and in the web dashboard footer."},
                ]
            },
        ]

        # Add a general info embed
        info_embed = discord.Embed(
            title="DND Flow Help",
            description="Use the commands below. Arguments in <> are required, those in () are optional. Autocomplete is available for dynamic arguments. Use tab or click to autocomplete where available.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=info_embed, ephemeral=True)

        # Send an embed for each command group
        for group in command_groups:
            embed = discord.Embed(title=f"{group['name']} Commands", description=group['description'], color=discord.Color.blurple())
            for cmd in group['commands']:
                embed.add_field(name=cmd['name'], value=cmd['desc'], inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Help(bot))

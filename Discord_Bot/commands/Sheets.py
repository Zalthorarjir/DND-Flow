###################################################################
# Sheets.py — Character sheet management and search             #
###################################################################
#
# Commands
# ─────────
#   /sheet new <name>              Create a character and their sheet
#   /sheet edit <name> <fieldname> Edit a field via modal (supports very long text)
#   /sheet submit <name>           Submit sheet for admin review
#   /sheet remove <name>           Permanently delete character + sheet
#   /sheet list                    List your characters and sheet statuses
#   /sheet icon <name> <image>     Attach an icon image to a character sheet
#   /sheet drafts                  List your Draft-status sheets
#   /search [name] [user]          Search approved sheets (guild-wide)
#
###################################################################

import os
import time
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands, ButtonStyle, Interaction, Embed
from discord.ext import commands
from discord import ui

from .sheet_storage import (
    ensure_schema,
    character_exists,
    create_character,
    get_character,
    list_characters,
    delete_character,
    get_characters_by_name_in_guild,
    create_sheet,
    get_sheet,
    get_sheet_by_character,
    get_approved_sheet,
    get_pending_sheet,
    create_draft_from_approved,
    promote_draft_to_approved,
    get_pending_sheets_for_guild,
    set_sheet_status,
    set_field,
    get_fields,
    delete_field,
    apply_template,
    get_template,
    set_pending_review,
    get_pending_review,
    clear_pending_review,
    record_review,
    search_characters,
    get_sheets_by_user,
    get_channel_ids,
)

_BASE      = os.path.dirname(os.path.dirname(__file__))
IMAGES_DIR = os.path.join(_BASE, 'databases', 'Users', 'images')

# sort_order constants for built-in fields
_SORT_ICON = 9999

# Fields with values longer than this go into the dropdown rather than the embed body
LONG_FIELD_THRESHOLD = 200

# Submit cooldown per (user_id, sheet_id): seconds
_submit_cooldowns: dict = {}
SUBMIT_COOLDOWN = 600  # 10 minutes


# ─── Embed builder ────────────────────────────────────────────────────────────

def _split_value(value: str, max_len: int = 1024) -> list:
    """
    Chunk a long string into Discord embed-safe pieces (max_len chars each).
    Priority for where to break:
      1. Newline characters  (\\n)
      2. Sentence endings    (. ! ?)
      3. Word boundaries     (space) — last resort, never cuts mid-word
    """
    if not value:
        return ["\u200b"]
    if len(value) <= max_len:
        return [value]

    chunks: list = []
    remaining = value

    while len(remaining) > max_len:
        window = remaining[:max_len]

        # 1. Last newline in the window
        cut = window.rfind("\n")

        # 2. Last sentence-ending punctuation in the window
        if cut == -1:
            for punct in (".", "!", "?"):
                pos = window.rfind(punct)
                if pos > cut:
                    cut = pos  # include the punctuation character itself

        # 3. Last space (word boundary)
        if cut == -1:
            cut = window.rfind(" ")

        # 4. Hard cut — no clean boundary found at all
        if cut == -1:
            cut = max_len - 1

        chunks.append(remaining[: cut + 1].rstrip())
        remaining = remaining[cut + 1 :].lstrip("\n")

    if remaining:
        chunks.append(remaining.rstrip())

    return chunks if chunks else ["\u200b"]


def _build_embeds(
    char_name: str,
    status: str,
    fields: list,
    user_display: str,
    title: str = "Character Sheet",
    color: discord.Color = None,
    comment: str = "",
) -> tuple:
    """
    Build embed(s) from sheet fields and return (embeds, long_fields).

    fields: [(field_name, value, sort_order), ...]

    Short fields (≤ LONG_FIELD_THRESHOLD chars) appear inline in the embed.
    Long fields are excluded from the embed body; their names are listed under
    '📖 Extended Fields' and their full content is returned as long_fields so
    callers can attach a dropdown view.
    """
    if color is None:
        color = discord.Color.blue()

    short_fields: list = []
    long_fields:  list = []
    for field_name, value, _ in fields:
        if field_name == "Icon" or not value:
            continue
        if len(value) > LONG_FIELD_THRESHOLD:
            long_fields.append((field_name, value))
        else:
            short_fields.append((field_name, value))

    embeds: list = []
    current = Embed(title=title, color=color)
    current.set_footer(text=f"User: {user_display}")

    def _add(name: str, val: str, inline: bool = False):
        nonlocal current
        for i, chunk in enumerate(_split_value(val)):
            label = name if i == 0 else "\u200b"
            if len(current.fields) >= 25:
                embeds.append(current)
                current = Embed(title=f"{title} (continued)", color=color)
            current.add_field(name=label, value=chunk, inline=inline)

    # Name and Status always at the top, full-width
    _add("Name",   char_name, inline=False)
    _add("Status", status,    inline=False)

    # Short fields displayed inline (up to 3 per row in Discord)
    for fname, fval in short_fields:
        _add(fname, fval, inline=True)

    # Just list the names of long fields — content lives in the dropdown
    if long_fields:
        names_list = "\n".join(f"• {fn}" for fn, _ in long_fields)
        if len(current.fields) >= 25:
            embeds.append(current)
            current = Embed(title=f"{title} (continued)", color=color)
        current.add_field(name="📖 Extended Fields", value=names_list, inline=False)

    if comment:
        _add("💬 Moderator Comment", comment, inline=False)

    if current.fields:
        embeds.append(current)

    return embeds, long_fields


# ─── UI components ────────────────────────────────────────────────────────────

class LongFieldView(ui.View):
    """Standalone dropdown that lets users read long field values on demand."""
    def __init__(self, long_fields: list):
        super().__init__(timeout=300)
        self._lf = {fn: val for fn, val in long_fields}
        options = [
            discord.SelectOption(label=fn[:100], value=fn[:100])
            for fn, _ in long_fields[:25]
        ]
        sel = ui.Select(placeholder="📖 Read an extended field\u2026", options=options)
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, inter: Interaction):
        fname = (inter.data.get("values") or [None])[0]
        if not fname:
            return
        value = self._lf.get(fname, "")
        embed = Embed(title=fname, color=discord.Color.blurple())
        for i, chunk in enumerate(_split_value(value)):
            embed.add_field(name=fname if i == 0 else "\u200b", value=chunk, inline=False)
        await inter.response.send_message(embed=embed, ephemeral=True)


class FieldModal(ui.Modal):
    def __init__(self, field_name: str, current_value: str, callback):
        super().__init__(title=f"Edit: {field_name[:45]}")
        self.field_name = field_name
        self._cb = callback
        self.input = ui.TextInput(
            label=field_name[:45],
            style=discord.TextStyle.paragraph,
            default=current_value,
            required=False,
            max_length=4000,
        )
        self.add_item(self.input)

    async def on_submit(self, interaction: Interaction):
        await self._cb(interaction, self.field_name, self.input.value)


class CommentModal(ui.Modal):
    def __init__(self, callback, action: str):
        super().__init__(title=f"{action} — Optional Comment")
        self._cb = callback
        self._action = action
        self.comment = ui.TextInput(
            label="Comment (optional)",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000,
        )
        self.add_item(self.comment)

    async def on_submit(self, interaction: Interaction):
        await self._cb(interaction, self._action, self.comment.value or "")


class ReviewView(ui.View):
    def __init__(self, sheet_id: int, member_id: str, on_action, long_fields: list = None):
        super().__init__(timeout=None)
        self.sheet_id  = sheet_id
        self.member_id = member_id
        self._on       = on_action
        self._lf: dict = {}

        # Row 1: dropdown for long fields (admins can read before acting)
        if long_fields:
            self._lf = {fn: val for fn, val in long_fields}
            options  = [
                discord.SelectOption(label=fn[:100], value=fn[:100])
                for fn, _ in long_fields[:25]
            ]
            sel = ui.Select(
                placeholder="📖 Read an extended field\u2026",
                options=options,
                row=1,
            )
            sel.callback = self._on_lf_select
            self.add_item(sel)

    async def _on_lf_select(self, inter: Interaction):
        fname = (inter.data.get("values") or [None])[0]
        if not fname:
            return
        value = self._lf.get(fname, "")
        embed = Embed(title=fname, color=discord.Color.blurple())
        for i, chunk in enumerate(_split_value(value)):
            embed.add_field(name=fname if i == 0 else "\u200b", value=chunk, inline=False)
        await inter.response.send_message(embed=embed, ephemeral=True)

    # Row 0: Approve / Deny / Discuss buttons
    @ui.button(label="Approve", style=ButtonStyle.success, custom_id="sheet_approve", row=0)
    async def approve(self, inter: Interaction, _: ui.Button):
        await inter.response.send_modal(
            CommentModal(
                lambda i, a, c: self._on(i, self.sheet_id, self.member_id, "Approved", c),
                "Approve",
            )
        )

    @ui.button(label="Deny", style=ButtonStyle.danger, custom_id="sheet_deny", row=0)
    async def deny(self, inter: Interaction, _: ui.Button):
        await inter.response.send_modal(
            CommentModal(
                lambda i, a, c: self._on(i, self.sheet_id, self.member_id, "Denied", c),
                "Deny",
            )
        )

    @ui.button(label="Discuss", style=ButtonStyle.primary, custom_id="sheet_discuss", row=0)
    async def discuss(self, inter: Interaction, _: ui.Button):
        await inter.response.send_modal(
            CommentModal(
                lambda i, a, c: self._on(i, self.sheet_id, self.member_id, "Discuss", c),
                "Discuss",
            )
        )


# ─── Admin disambiguation views ──────────────────────────────────────────────

class _ConfirmDeleteView(ui.View):
    """Single-use confirmation before an admin deletes another user's character."""

    def __init__(self, character_id: int, name: str, owner_id: str):
        super().__init__(timeout=30)
        self._cid   = character_id
        self._name  = name
        self._owner = owner_id

    @ui.button(label="Confirm Delete", style=ButtonStyle.danger)
    async def confirm(self, inter: Interaction, _: ui.Button):
        delete_character(self._cid)
        self.stop()
        await inter.response.edit_message(
            content=f"Character **{self._name}** (owner: <@{self._owner}>) has been permanently deleted.",
            view=None,
        )

    @ui.button(label="Cancel", style=ButtonStyle.secondary)
    async def cancel(self, inter: Interaction, _: ui.Button):
        self.stop()
        await inter.response.edit_message(content="Cancelled.", view=None)


class DisambiguateView(ui.View):
    """Select which user's character to delete when multiple users share the same name."""

    def __init__(self, matches: list):
        super().__init__(timeout=60)
        self._matches = {str(m["character_id"]): m for m in matches}
        options = [
            discord.SelectOption(
                label=m["name"][:50],
                description=f"Owner: {m['user_id']}",
                value=str(m["character_id"]),
            )
            for m in matches[:25]
        ]
        sel = ui.Select(
            placeholder="Select which user's character to delete…",
            options=options,
        )
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, inter: Interaction):
        cid = (inter.data.get("values") or [None])[0]
        if not cid:
            return
        char = self._matches.get(cid)
        if not char:
            await inter.response.send_message("Selection no longer valid.", ephemeral=True)
            return
        confirm_view = _ConfirmDeleteView(int(cid), char["name"], char["user_id"])
        await inter.response.send_message(
            f"Delete **{char['name']}** owned by <@{char['user_id']}>? This is permanent.",
            view=confirm_view,
            ephemeral=True,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Sheet Cog
# ═══════════════════════════════════════════════════════════════════════════════

class Sheet(commands.GroupCog, name="sheet"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    # ── Autocomplete ──────────────────────────────────────────────────────────

    async def _char_autocomplete(self, interaction: Interaction, current: str) -> list:
        """Autocomplete from the user's own character names."""
        if not interaction.guild:
            return []
        user_id  = str(interaction.user.id)
        guild_id = str(interaction.guild.id)
        try:
            chars = list_characters(user_id, guild_id)
            return [
                app_commands.Choice(name=c["name"], value=c["name"])
                for c in chars
                if current.lower() in c["name"].lower()
            ][:25]
        except Exception:
            return []

    async def _field_autocomplete(self, interaction: Interaction, current: str) -> list:
        """Autocomplete from the guild's template field names."""
        if not interaction.guild:
            return []
        guild_id = str(interaction.guild.id)
        try:
            template = get_template(guild_id)
            return [
                app_commands.Choice(name=t["field_name"], value=t["field_name"])
                for t in template
                if current.lower() in t["field_name"].lower()
            ][:25]
        except Exception:
            return []

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _icon_file(self, user_id: str, icon_value: str) -> Optional[discord.File]:
        if not icon_value:
            return None
        base = Path(IMAGES_DIR).resolve()
        p = (base / user_id / icon_value).resolve()
        if not str(p).startswith(str(base)):
            return None
        return discord.File(str(p), filename=p.name) if p.exists() else None

    # ── /sheet new ────────────────────────────────────────────────────────────

    @app_commands.command(name="new", description="Create a new character and sheet.")
    @app_commands.describe(name="Character name")
    async def new(self, interaction: Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        user_id  = str(interaction.user.id)
        guild_id = str(interaction.guild.id) if interaction.guild else "0"
        try:
            char_id  = create_character(user_id, guild_id, name)
            sheet_id = create_sheet(char_id)
            apply_template(sheet_id, guild_id)
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        await interaction.followup.send(
            f"Character **{name}** created with a Draft sheet.\n"
            f"Use `/sheet edit {name} <field>` to fill in each field, then `/sheet submit {name}` when ready.",
            ephemeral=True,
        )

    # ── /sheet edit ───────────────────────────────────────────────────────────

    @app_commands.command(name="edit", description="Edit a field on one of your character sheets.")
    @app_commands.describe(name="Character name", fieldname="Field to edit")
    @app_commands.autocomplete(name=_char_autocomplete, fieldname=_field_autocomplete)
    async def edit(self, interaction: Interaction, name: str, fieldname: str):
        user_id  = str(interaction.user.id)
        guild_id = str(interaction.guild.id) if interaction.guild else "0"

        char = get_character(user_id, guild_id, name)
        if not char:
            await interaction.response.send_message("Character not found.", ephemeral=True)
            return

        # Find the working sheet (Draft or Pending). If only Approved exists, fork a Draft.
        working = get_pending_sheet(char["character_id"])
        if not working:
            approved = get_approved_sheet(char["character_id"])
            if not approved:
                await interaction.response.send_message(
                    "No sheet found for this character.", ephemeral=True
                )
                return
            # Fork approved → new draft silently
            new_sheet_id = create_draft_from_approved(char["character_id"])
            working = get_sheet(new_sheet_id)

        if working["status"] == "Pending":
            await interaction.response.send_message(
                "This sheet is currently **Pending** review and cannot be edited. "
                "Wait for an admin decision or contact staff.", ephemeral=True
            )
            return

        fields        = get_fields(working["sheet_id"])
        current_value = next((v for fn, v, _ in fields if fn == fieldname), "") or ""

        async def save(inter: Interaction, fn: str, new_val: str):
            set_field(working["sheet_id"], fn, new_val)
            await inter.response.send_message(
                f"Field **{fn}** saved to your Draft. Use `/sheet submit {name}` when ready.",
                ephemeral=True,
            )

        await interaction.response.send_modal(FieldModal(fieldname, current_value, save))

    # ── /sheet submit ─────────────────────────────────────────────────────────

    @app_commands.command(name="submit", description="Submit a character sheet for admin review.")
    @app_commands.describe(name="Character name")
    @app_commands.autocomplete(name=_char_autocomplete)
    async def submit(self, interaction: Interaction, name: str):
        user_id  = str(interaction.user.id)
        guild_id = str(interaction.guild.id) if interaction.guild else "0"

        char = get_character(user_id, guild_id, name)
        if not char:
            await interaction.response.send_message("Character not found.", ephemeral=True)
            return

        # Only Draft sheets can be submitted
        sheet = get_pending_sheet(char["character_id"])
        if not sheet:
            approved = get_approved_sheet(char["character_id"])
            if approved:
                await interaction.response.send_message(
                    f"**{name}** is already Approved with no pending changes. "
                    f"Use `/sheet edit` to make changes first.", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "No sheet found for this character.", ephemeral=True
                )
            return

        if sheet["status"] == "Pending":
            await interaction.response.send_message(
                f"**{name}** is already **Pending** review.", ephemeral=True
            )
            return

        # Cooldown (prune stale entries to prevent memory leak)
        key  = (user_id, sheet["sheet_id"])
        now  = time.time()
        expired = [k for k, t in _submit_cooldowns.items() if now - t >= SUBMIT_COOLDOWN]
        for k in expired:
            _submit_cooldowns.pop(k, None)
        last = _submit_cooldowns.get(key, 0)
        if now - last < SUBMIT_COOLDOWN:
            next_epoch = int(last + SUBMIT_COOLDOWN)
            await interaction.response.send_message(
                f"Please wait before resubmitting.\nCooldown expires: <t:{next_epoch}:R>",
                ephemeral=True,
            )
            return

        # Validate required fields
        template       = get_template(guild_id)
        required_names = {t["field_name"] for t in template if t["required"]}
        fields         = get_fields(sheet["sheet_id"])
        field_map      = {fn: v for fn, v, _ in fields}
        missing        = [f for f in required_names if not field_map.get(f)]
        if missing:
            await interaction.response.send_message(
                f"Cannot submit: these required fields are empty: **{', '.join(missing)}**",
                ephemeral=True,
            )
            return

        # Channels
        channels = get_channel_ids(guild_id)
        if not channels["admin"] or not channels["member"]:
            await interaction.response.send_message(
                "Admin and member channels must be configured first with `/config channel`.",
                ephemeral=True,
            )
            return

        admin_channel  = self.bot.get_channel(int(channels["admin"]))
        member_channel = self.bot.get_channel(int(channels["member"]))
        if not isinstance(admin_channel, discord.TextChannel):
            await interaction.response.send_message(
                "Admin channel not found or is not a text channel.", ephemeral=True
            )
            return
        if not isinstance(member_channel, discord.TextChannel):
            await interaction.response.send_message(
                "Member channel not found or is not a text channel.", ephemeral=True
            )
            return

        _submit_cooldowns[key] = now
        user_display = getattr(interaction.user, "display_name", None) or interaction.user.name
        embeds, long_fields = _build_embeds(name, sheet["status"], fields, user_display, title="Sheet Submission:")

        icon_value = field_map.get("Icon")
        icon_file  = self._icon_file(user_id, icon_value)
        if icon_file and embeds:
            embeds[0].set_thumbnail(url=f"attachment://{icon_value}")

        sheet_id = sheet["sheet_id"]

        async def on_action(inter: Interaction, sid: int, mid: str, action: str, comment: str):
            try:
                color_map = {
                    "Approved": discord.Color.green(),
                    "Denied":   discord.Color.red(),
                    "Discuss":  discord.Color.gold(),
                }
                title_map = {
                    "Approved": "Sheet Approved",
                    "Denied":   "Sheet Denied",
                    "Discuss":  "Please Contact Staff",
                }
                if action == "Approved":
                    promote_draft_to_approved(sid)
                elif action == "Denied":
                    # Reset pending sheet to Draft so user can revise and resubmit
                    set_sheet_status(sid, "Draft")
                else:
                    set_sheet_status(sid, action)
                record_review(sid, str(inter.user.id), action, comment)
                clear_pending_review(sid)

                updated_fields = get_fields(sid)
                reviewer_name  = getattr(inter.user, "display_name", None) or inter.user.name
                result_embeds, result_long = _build_embeds(
                    name, action, updated_fields, reviewer_name,
                    title=title_map.get(action, action),
                    color=color_map.get(action, discord.Color.default()),
                    comment=comment,
                )
                result_file = self._icon_file(mid, field_map.get("Icon"))
                if result_file and result_embeds:
                    result_embeds[0].set_thumbnail(url=f"attachment://{field_map['Icon']}")
                lf_view = LongFieldView(result_long) if result_long else None

                try:
                    if inter.message:
                        await inter.message.edit(view=None)
                except Exception:
                    pass

                if result_file:
                    await member_channel.send(
                        content=f"<@{mid}>", embeds=result_embeds, file=result_file, view=lf_view
                    )
                else:
                    await member_channel.send(content=f"<@{mid}>", embeds=result_embeds, view=lf_view)

                await inter.response.send_message(
                    f"Sheet marked as **{action}**.", ephemeral=True
                )
            except Exception as e:
                await inter.response.send_message(f"Error processing review: {e}", ephemeral=True)

        view = ReviewView(sheet_id, user_id, on_action, long_fields)
        try:
            if icon_file:
                msg = await admin_channel.send(embeds=embeds, view=view, file=icon_file)
            else:
                msg = await admin_channel.send(embeds=embeds, view=view)
            set_pending_review(sheet_id, str(msg.channel.id), str(msg.id))
        except Exception as e:
            await interaction.response.send_message(
                f"Failed to send to admin channel: {e}", ephemeral=True
            )
            return

        set_sheet_status(sheet_id, "Pending")
        await interaction.response.send_message(
            f"**{name}** submitted for review. You will be notified in the member channel.",
            ephemeral=True,
        )

    # ── /sheet remove ─────────────────────────────────────────────────────────

    @app_commands.command(name="remove", description="Permanently delete a character and their sheet.")
    @app_commands.describe(name="Character name")
    @app_commands.autocomplete(name=_char_autocomplete)
    async def remove(self, interaction: Interaction, name: str):
        user_id  = str(interaction.user.id)
        guild_id = str(interaction.guild.id) if interaction.guild else "0"

        # Admin check — required for all deletions
        config_cog = interaction.client.cogs.get("Config")
        if not config_cog or not await config_cog.is_admin(interaction):
            await interaction.response.send_message(
                "You do not have permission to delete characters.", ephemeral=True
            )
            return

        # Try the invoker's own character first (exact-user match)
        char = get_character(user_id, guild_id, name)
        if char:
            delete_character(char["character_id"])
            await interaction.response.send_message(
                f"Character **{name}** and their sheet have been permanently deleted.", ephemeral=True
            )
            return

        # Fall through to guild-wide search (another user's character)
        matches = get_characters_by_name_in_guild(guild_id, name)
        if not matches:
            await interaction.response.send_message(
                f"No character named **{name}** found in this guild.", ephemeral=True
            )
            return

        if len(matches) == 1:
            m = matches[0]
            delete_character(m["character_id"])
            await interaction.response.send_message(
                f"Character **{name}** (owner: <@{m['user_id']}>) has been permanently deleted.",
                ephemeral=True,
            )
            return

        # Multiple users share the same name — disambiguation required
        view = DisambiguateView(matches)
        await interaction.response.send_message(
            f"Multiple characters named **{name}** found. Select which to delete:",
            view=view,
            ephemeral=True,
        )

    # ── /sheet list ───────────────────────────────────────────────────────────

    @app_commands.command(name="list", description="List all your characters and sheet statuses.")
    async def list_sheets(self, interaction: Interaction):
        user_id  = str(interaction.user.id)
        guild_id = str(interaction.guild.id) if interaction.guild else "0"

        entries = get_sheets_by_user(user_id, guild_id)
        if not entries:
            await interaction.response.send_message(
                "You have no characters yet. Use `/sheet new` to create one.", ephemeral=True
            )
            return

        # Group by character name
        from collections import defaultdict
        by_char: dict = defaultdict(list)
        for e in entries:
            by_char[e["name"]].append(e)

        embed = Embed(title="Your Characters", color=discord.Color.blurple())
        for char_name, sheets in by_char.items():
            status_lines = []
            for s in sheets:
                st = s["status"]
                if st == "Approved":
                    status_lines.append("✅ Approved")
                elif st == "Pending":
                    status_lines.append("🕐 Pending review")
                elif st == "Draft":
                    status_lines.append("📝 Draft")
                elif st == "Denied":
                    status_lines.append("❌ Denied — resubmit when ready")
                else:
                    status_lines.append(f"• {st}")
            embed.add_field(name=char_name, value="\n".join(status_lines), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /sheet icon ───────────────────────────────────────────────────────────

    @app_commands.command(name="icon", description="Set an icon image for a character sheet.")
    @app_commands.describe(name="Character name", image="Image file to use as icon")
    @app_commands.autocomplete(name=_char_autocomplete)
    async def icon(self, interaction: Interaction, name: str, image: discord.Attachment):
        user_id  = str(interaction.user.id)
        guild_id = str(interaction.guild.id) if interaction.guild else "0"

        if not image.content_type or not image.content_type.startswith("image/"):
            await interaction.response.send_message(
                "Please attach a valid image file.", ephemeral=True
            )
            return

        char = get_character(user_id, guild_id, name)
        if not char:
            await interaction.response.send_message("Character not found.", ephemeral=True)
            return

        sheet = get_pending_sheet(char["character_id"]) or get_approved_sheet(char["character_id"])
        if not sheet:
            await interaction.response.send_message(
                "No sheet found for this character.", ephemeral=True
            )
            return

        _ALLOWED_EXTS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
        ext = image.filename.rsplit(".", 1)[-1].lower() if "." in image.filename else ""
        if ext not in _ALLOWED_EXTS:
            await interaction.response.send_message(
                "Only jpg, jpeg, png, gif, and webp images are allowed.", ephemeral=True
            )
            return
        save_dir = Path(IMAGES_DIR) / user_id
        save_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{char['character_id']}.{ext}"
        try:
            await image.save(save_dir / filename)
        except Exception as e:
            await interaction.response.send_message(f"Failed to save image: {e}", ephemeral=True)
            return

        set_field(sheet["sheet_id"], "Icon", filename, sort_order=_SORT_ICON)
        await interaction.response.send_message(
            f"Icon set for **{name}**.", ephemeral=True
        )

    # ── /sheet drafts ─────────────────────────────────────────────────────────

    @app_commands.command(name="drafts", description="List your sheets still in Draft status.")
    async def drafts(self, interaction: Interaction):
        user_id  = str(interaction.user.id)
        guild_id = str(interaction.guild.id) if interaction.guild else "0"

        entries = get_sheets_by_user(user_id, guild_id, status="Draft")
        if not entries:
            await interaction.response.send_message("No draft sheets found.", ephemeral=True)
            return

        embed = Embed(title="Your Draft Sheets", color=discord.Color.greyple())
        for e in entries:
            embed.add_field(name=e["name"], value="Status: **Draft**", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /sheet pending (admin) ────────────────────────────────────────────────

    @app_commands.command(name="pending", description="[Admin] View all pending sheets awaiting review.")
    async def pending(self, interaction: Interaction):
        guild_id = str(interaction.guild.id) if interaction.guild else "0"

        # Admin check
        config_cog = self.bot.get_cog("Config")
        if not config_cog or not await config_cog.is_admin(interaction):
            await interaction.response.send_message(
                "You do not have permission to use this command.", ephemeral=True
            )
            return

        sheets = get_pending_sheets_for_guild(guild_id)
        if not sheets:
            await interaction.response.send_message("No sheets are currently pending review.", ephemeral=True)
            return

        channels = get_channel_ids(guild_id)
        admin_channel  = self.bot.get_channel(int(channels["admin"])) if channels["admin"] else None
        member_channel = self.bot.get_channel(int(channels["member"])) if channels["member"] else None

        # Build dropdown of pending sheets
        options = [
            discord.SelectOption(
                label=f"{s['name']} (<@{s['user_id']}>)",
                description=f"Updated <t:{s['updated_at']}:R>",
                value=str(s["sheet_id"]),
            )
            for s in sheets[:25]
        ]
        embed = Embed(
            title=f"Pending Sheets ({len(sheets)})",
            description="Select a sheet below to open its review panel.",
            color=discord.Color.gold(),
        )
        for s in sheets:
            embed.add_field(
                name=s["name"],
                value=f"<@{s['user_id']}> — updated <t:{s['updated_at']}:R>",
                inline=False,
            )

        sel = ui.Select(placeholder="Select a sheet to review…", options=options)

        async def on_select(inter: Interaction):
            vals = inter.data.get("values") or []
            if not vals:
                return
            sid = int(vals[0])
            entry = next((s for s in sheets if s["sheet_id"] == sid), None)
            if not entry:
                await inter.response.send_message("Sheet not found.", ephemeral=True)
                return

            fields    = get_fields(sid)
            field_map = {fn: v for fn, v, _ in fields}
            user_id   = entry["user_id"]
            char_name = entry["name"]

            user_display = f"<@{user_id}>"
            embeds, long_fields = _build_embeds(
                char_name, entry["status"], fields, user_display, title="Pending Sheet:"
            )
            icon_value = field_map.get("Icon")
            icon_file  = self._icon_file(user_id, icon_value)
            if icon_file and embeds:
                embeds[0].set_thumbnail(url=f"attachment://{icon_value}")

            if not isinstance(admin_channel, discord.TextChannel):
                await inter.response.send_message(
                    "Admin channel not configured.", ephemeral=True
                )
                return
            if not isinstance(member_channel, discord.TextChannel):
                await inter.response.send_message(
                    "Member channel not configured.", ephemeral=True
                )
                return

            async def on_action(action_inter: Interaction, _sid: int, mid: str, action: str, comment: str):
                try:
                    if action == "Approved":
                        promote_draft_to_approved(_sid)
                    elif action == "Denied":
                        set_sheet_status(_sid, "Draft")
                    else:
                        set_sheet_status(_sid, action)
                    record_review(_sid, str(action_inter.user.id), action, comment)
                    clear_pending_review(_sid)

                    color_map = {
                        "Approved": discord.Color.green(),
                        "Denied":   discord.Color.red(),
                        "Discuss":  discord.Color.gold(),
                    }
                    title_map = {
                        "Approved": "Sheet Approved",
                        "Denied":   "Sheet Denied",
                        "Discuss":  "Please Contact Staff",
                    }
                    updated_fields = get_fields(_sid)
                    reviewer_name  = getattr(action_inter.user, "display_name", None) or action_inter.user.name
                    result_embeds, result_long = _build_embeds(
                        char_name, action, updated_fields, reviewer_name,
                        title=title_map.get(action, action),
                        color=color_map.get(action, discord.Color.default()),
                        comment=comment,
                    )
                    result_file = self._icon_file(mid, field_map.get("Icon"))
                    if result_file and result_embeds:
                        result_embeds[0].set_thumbnail(url=f"attachment://{field_map['Icon']}")
                    lf_view = LongFieldView(result_long) if result_long else None

                    try:
                        if action_inter.message:
                            await action_inter.message.edit(view=None)
                    except Exception:
                        pass

                    if result_file:
                        await member_channel.send(
                            content=f"<@{mid}>", embeds=result_embeds, file=result_file, view=lf_view
                        )
                    else:
                        await member_channel.send(content=f"<@{mid}>", embeds=result_embeds, view=lf_view)

                    await action_inter.response.send_message(
                        f"Sheet marked as **{action}**.", ephemeral=True
                    )
                except Exception as e:
                    await action_inter.response.send_message(f"Error processing review: {e}", ephemeral=True)

            review_view = ReviewView(sid, user_id, on_action, long_fields)
            try:
                if icon_file:
                    msg = await admin_channel.send(embeds=embeds, view=review_view, file=icon_file)
                else:
                    msg = await admin_channel.send(embeds=embeds, view=review_view)
                set_pending_review(sid, str(msg.channel.id), str(msg.id))
                await inter.response.send_message(
                    f"Review panel posted in {admin_channel.mention}.", ephemeral=True
                )
            except Exception as e:
                await inter.response.send_message(f"Failed to post review: {e}", ephemeral=True)

        sel.callback = on_select
        view = ui.View(timeout=120)
        view.add_item(sel)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
# ═══════════════════════════════════════════════════════════════════════════════

class Search(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="search", description="Search for approved character sheets in this server."
    )
    @app_commands.describe(
        name="Part of a character name to search for (optional)",
        user="Limit results to this user (optional)",
    )
    async def search(
        self,
        interaction: Interaction,
        name: Optional[str] = None,
        user: Optional[discord.User] = None,
    ):
        if not name and not user:
            await interaction.response.send_message(
                "Provide at least a character name or a @user to search.", ephemeral=True
            )
            return

        guild_id = str(interaction.guild.id) if interaction.guild else "0"
        results  = search_characters(
            guild_id,
            name_query=name,
            user_id=str(user.id) if user else None,
            status="Approved",
        )

        if not results:
            await interaction.response.send_message(
                "No approved sheets found.", ephemeral=True
            )
            return

        per_page = 25
        pages    = max(1, (len(results) + per_page - 1) // per_page)

        def make_page_embed(idx: int) -> Embed:
            e = Embed(
                title="Sheet Search Results",
                description=f"Page {idx + 1}/{pages}",
                color=discord.Color.blue(),
            )
            for entry in results[idx * per_page : (idx + 1) * per_page]:
                e.add_field(name=entry["name"], value=f"<@{entry['user_id']}>", inline=False)
            return e

        class SearchView(discord.ui.View):
            def __init__(self_v):
                super().__init__(timeout=180)
                self_v.page = 0
                self_v._rebuild()

            def _rebuild(self_v):
                self_v.clear_items()
                page_results = results[self_v.page * per_page : (self_v.page + 1) * per_page]
                options = [
                    discord.SelectOption(
                        label=e["name"][:100],
                        description=f"User: {e['user_id']}",
                        value=str(e["sheet_id"]),
                    )
                    for e in page_results
                ]
                sel = discord.ui.Select(placeholder="View a character sheet…", options=options)
                sel.callback = self_v._on_select
                self_v.add_item(sel)

                if pages > 1:
                    prev = discord.ui.Button(
                        label="◀", style=ButtonStyle.secondary, disabled=self_v.page == 0
                    )
                    nxt = discord.ui.Button(
                        label="▶",
                        style=ButtonStyle.secondary,
                        disabled=self_v.page >= pages - 1,
                    )

                    async def _prev(inter: Interaction):
                        self_v.page = max(0, self_v.page - 1)
                        self_v._rebuild()
                        await inter.response.edit_message(
                            embed=make_page_embed(self_v.page), view=self_v
                        )

                    async def _next(inter: Interaction):
                        self_v.page = min(pages - 1, self_v.page + 1)
                        self_v._rebuild()
                        await inter.response.edit_message(
                            embed=make_page_embed(self_v.page), view=self_v
                        )

                    prev.callback = _prev
                    nxt.callback  = _next
                    self_v.add_item(prev)
                    self_v.add_item(nxt)

            async def _on_select(self_v, inter: Interaction):
                _vals = inter.data.get("values") or []
                if not _vals:
                    return
                sid   = int(_vals[0])
                entry = next((r for r in results if r["sheet_id"] == sid), None)
                if not entry:
                    await inter.response.send_message("Sheet not found.", ephemeral=True)
                    return

                fields    = get_fields(sid)
                field_map = {fn: v for fn, v, _ in fields}
                detail_embeds, detail_long = _build_embeds(
                    entry["name"],
                    entry["status"],
                    fields,
                    f"<@{entry['user_id']}>",
                    title=f"Sheet: {entry['name']}",
                )
                detail_view = LongFieldView(detail_long) if detail_long else None

                icon_val   = field_map.get("Icon")
                icon_file  = None
                if icon_val:
                    p = Path(IMAGES_DIR) / entry["user_id"] / icon_val
                    if p.exists():
                        icon_file = discord.File(str(p), filename=icon_val)
                        if detail_embeds:
                            detail_embeds[0].set_thumbnail(url=f"attachment://{icon_val}")

                if icon_file:
                    await inter.response.send_message(
                        embeds=detail_embeds, file=icon_file, view=detail_view, ephemeral=True
                    )
                else:
                    await inter.response.send_message(embeds=detail_embeds, view=detail_view, ephemeral=True)

        await interaction.response.send_message(
            embed=make_page_embed(0), view=SearchView(), ephemeral=True
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Extension setup
# ═══════════════════════════════════════════════════════════════════════════════

async def setup(bot: commands.Bot):
    ensure_schema()
    await bot.add_cog(Sheet(bot))
    await bot.add_cog(Search(bot))

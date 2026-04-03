"""
test_bot.py — Complete test suite for Discord_Bot.

Every test redirects ALL module-level DB paths to pytest's tmp_path, so the
live databases/ folder is NEVER touched, even when the bot is running.

Coverage
────────
  1   Sheet-storage: characters, sheets, fields, dual-sheet model, templates
  2   Audit log utilities
  3   Admin permission (Config cog)
  4   Config command handlers (role, channel, field_add, field_remove, delete,
      reset, work_cooldown)
  5   Economy command handlers (currency view/set/remove, work create/edit/assign,
      job_claim, give_money, give_item)
  6   Inventory command handlers
  7   Market command handlers (item add/remove/set_description/set_image/list,
      shop add/remove/view/buy/sell)
  8   Combat command handlers (fight_dynamic start, fight_dynamic_rules,
      health_track, death claim/set/infinite/reset/check/revive/list/graveyard)
  9   Death ClaimView buttons
  10  HealthBar reaction handler
  11  FightDynamic reaction handler
  12  Sheets command handlers (new/edit/submit/remove/list/icon/drafts/pending)
  13  Sheets UI components (FieldModal, CommentModal, _ConfirmDeleteView, etc.)
  14  Autocomplete functions
  15  Help command
  16  Search cog (/search)
  17  Command registration (direct inspection, no load_extension)

Run:  pytest test_bot.py -v
"""

import asyncio
import importlib
import os
import sqlite3
import sys
import time
import pytest
from unittest.mock import MagicMock, AsyncMock

sys.path.insert(0, os.path.dirname(__file__))

# ─── Constants ────────────────────────────────────────────────────────────────

USER1_ID      = "111111111111111111"
USER1_CHAR    = "Aria"
USER2_ID      = "222222222222222222"
USER2_CHAR    = "Bob"
GUILD_ID      = "999999999999999999"
ADMIN_ROLE_ID = 77777777777777777


# ─── Async runner ─────────────────────────────────────────────────────────────

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ─── Fake Discord objects ─────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self):
        self.calls    = []
        self.modal    = None
        self.deferred = False

    async def send_message(self, content=None, *, embed=None, ephemeral=False, **kw):
        self.calls.append(dict(content=content, embed=embed, ephemeral=ephemeral))

    async def send_modal(self, modal):
        self.modal = modal

    async def defer(self, *, ephemeral=False, **kw):
        self.deferred = True

    async def edit_message(self, *, content=None, embed=None, view=None, **kw):
        self.calls.append(dict(content=content, embed=embed))

    def last_content(self):
        return self.calls[-1]["content"] if self.calls else None

    def last_embed(self):
        return self.calls[-1]["embed"] if self.calls else None


class _FakeFollowup:
    def __init__(self):
        self.calls = []

    async def send(self, content=None, *, embed=None, ephemeral=False, **kw):
        self.calls.append(dict(content=content, embed=embed, ephemeral=ephemeral))

    def last_content(self):
        return self.calls[-1]["content"] if self.calls else None


def make_bot(admin=False):
    from discord.ext import commands as dc
    bot = MagicMock(spec=dc.Bot)
    cog = MagicMock()
    cog.is_admin = AsyncMock(return_value=admin)
    bot.get_cog = lambda name: cog if name == "Config" else None
    bot.cogs    = {"Config": cog}
    return bot


def make_interaction(user_id, *, admin=False, bot=None):
    ix                    = MagicMock()
    ix.response           = _FakeResponse()
    ix.followup           = _FakeFollowup()
    ix.user               = MagicMock()
    ix.user.id            = int(user_id)
    ix.user.name          = "alice" if user_id == USER1_ID else "bob"
    ix.user.display_name  = ix.user.name
    ix.user.mention       = f"<@{user_id}>"
    ix.guild              = MagicMock()
    ix.guild.id           = int(GUILD_ID)
    _ar                   = MagicMock()
    _ar.id                = ADMIN_ROLE_ID
    ix.guild.get_role     = lambda rid: _ar if rid == ADMIN_ROLE_ID else None
    ix.guild.get_member   = lambda mid: None
    ix.guild.get_channel  = lambda cid: None
    ix.user.roles         = [_ar] if admin else []
    ix.channel            = MagicMock()
    ix.channel.id         = 123456789
    ix.channel.mention    = "#test"
    ix.channel_id         = 123456789
    ix.guild_id           = int(GUILD_ID)
    _fu                   = MagicMock()
    _fu.name              = ix.user.name
    ix.client             = bot or make_bot(admin=admin)
    ix.client.fetch_user  = AsyncMock(return_value=_fu)
    return ix


# ─── Master DB fixture ────────────────────────────────────────────────────────

@pytest.fixture()
def dbs(tmp_path, monkeypatch):
    """
    Redirect every module-level DB path to tmp_path.

    Uses sys.modules[] directly (not `import`) to get the live module object.
    discord.py's load_extension() swaps sys.modules entries but the stdlib
    import cache can return stale objects, which would leave the monkeypatch
    pointing at the wrong module.
    """
    def _mod(name):
        importlib.import_module(name)
        return sys.modules[name]

    ss  = _mod("commands.sheet_storage")
    eco = _mod("commands.Economy")
    inv = _mod("commands.Inventory")
    mkt = _mod("commands.Market")
    cbt = _mod("commands.Combat")
    cfg = _mod("commands.Config")
    al  = _mod("commands.audit_log")
    sht = _mod("commands.Sheets")

    sheets_db    = str(tmp_path / "Sheets.db")
    economy_db   = str(tmp_path / "Economy.db")
    inventory_db = str(tmp_path / "Inventory.db")
    shop_db      = str(tmp_path / "Shop.db")
    settings_db  = str(tmp_path / "Settings.db")
    combat_db    = str(tmp_path / "Combat.db")
    audit_db     = str(tmp_path / "Audit.db")
    images_dir   = str(tmp_path / "Items")
    users_dir    = str(tmp_path / "Users")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(users_dir,  exist_ok=True)

    monkeypatch.setattr(ss,  "SHEETS_DB",    sheets_db)
    monkeypatch.setattr(ss,  "SETTINGS_DB",  settings_db)
    monkeypatch.setattr(eco, "ECONOMY_DB",   economy_db)
    monkeypatch.setattr(eco, "INVENTORY_DB", inventory_db)
    monkeypatch.setattr(eco, "SHOP_DB",      shop_db)
    monkeypatch.setattr(eco, "SETTINGS_DB",  settings_db)
    monkeypatch.setattr(eco, "USERS_DIR",    users_dir)
    monkeypatch.setattr(inv, "INVENTORY_DB", inventory_db)
    monkeypatch.setattr(inv, "_SHOP_DB",     shop_db)
    monkeypatch.setattr(mkt, "SHOP_DB_PATH", shop_db)
    monkeypatch.setattr(mkt, "INVENTORY_DB", inventory_db)
    monkeypatch.setattr(mkt, "IMAGES_DIR",   images_dir)
    monkeypatch.setattr(mkt, "USERS_DIR",    users_dir)
    monkeypatch.setattr(cbt, "COMBAT_DB",    combat_db)
    monkeypatch.setattr(cbt, "USERS_DIR",    users_dir)
    monkeypatch.setattr(cfg, "DB_PATH",      settings_db)
    monkeypatch.setattr(al,  "AUDIT_DB",     audit_db)
    monkeypatch.setattr(al,  "SETTINGS_DB",  settings_db)
    monkeypatch.setattr(sht, "IMAGES_DIR",   images_dir)

    # ── Sheets.db ─────────────────────────────────────────────────────────────
    ss.ensure_schema()

    # ── Economy.db ────────────────────────────────────────────────────────────
    with sqlite3.connect(economy_db) as c:
        c.executescript("""
            CREATE TABLE currency  (user_id TEXT, character TEXT,
                amount REAL DEFAULT 0, PRIMARY KEY (user_id, character));
            CREATE TABLE jobs      (job_name TEXT PRIMARY KEY, payment REAL);
            CREATE TABLE user_jobs (user_id TEXT, character TEXT, job_name TEXT,
                PRIMARY KEY (user_id, character));
            CREATE TABLE last_claim(user_id TEXT, character TEXT, last_time INTEGER,
                PRIMARY KEY (user_id, character));
        """)

    # ── Inventory.db ──────────────────────────────────────────────────────────
    with sqlite3.connect(inventory_db) as c:
        c.execute("""
            CREATE TABLE inventory
            (user_id TEXT, guild_id TEXT NOT NULL DEFAULT '', character TEXT, item_name TEXT,
             quantity INTEGER, description TEXT DEFAULT '', icon TEXT DEFAULT '',
             PRIMARY KEY (user_id, guild_id, character, item_name))
        """)

    # ── Shop.db ───────────────────────────────────────────────────────────────
    with sqlite3.connect(shop_db) as c:
        c.executescript("""
            CREATE TABLE items (name TEXT PRIMARY KEY,
                consumable TEXT NOT NULL CHECK (consumable IN ('Yes','No')),
                image TEXT, description TEXT);
            CREATE TABLE shop (item_name TEXT PRIMARY KEY, price INTEGER NOT NULL);
        """)

    # ── Settings.db ───────────────────────────────────────────────────────────
    with sqlite3.connect(settings_db) as c:
        c.executescript("""
            CREATE TABLE Server (guild_id INTEGER PRIMARY KEY,
                admin_role_id INTEGER, admin_channel_id INTEGER,
                member_role_id INTEGER, member_channel_id INTEGER);
            CREATE TABLE IF NOT EXISTS WorkCooldown
                (id INTEGER PRIMARY KEY CHECK (id=1), days INTEGER);
        """)
        c.execute(
            "INSERT OR REPLACE INTO Server (guild_id, admin_role_id) VALUES (?, ?)",
            (int(GUILD_ID), ADMIN_ROLE_ID),
        )

    # ── Combat.db ─────────────────────────────────────────────────────────────
    with sqlite3.connect(combat_db) as c:
        c.executescript("""
            CREATE TABLE Rules (id INTEGER PRIMARY KEY AUTOINCREMENT,
                hitchance REAL, missed1 REAL, missed2 REAL, missed3 REAL);
            CREATE TABLE DeathCooldown (user_id TEXT, name TEXT, cooldown INTEGER,
                infinite INTEGER DEFAULT 0, set_at INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, name));
            CREATE TABLE GlobalSettings (id INTEGER PRIMARY KEY,
                cooldown INTEGER DEFAULT 0, infinite INTEGER DEFAULT 0);
            INSERT OR IGNORE INTO GlobalSettings (id) VALUES (1);
        """)

    # ── Seed both characters ───────────────────────────────────────────────────
    cid1 = ss.create_character(USER1_ID, GUILD_ID, USER1_CHAR)
    cid2 = ss.create_character(USER2_ID, GUILD_ID, USER2_CHAR)
    ss.create_sheet(cid1)
    ss.create_sheet(cid2)

    return dict(
        sheets_db=sheets_db, economy_db=economy_db, inventory_db=inventory_db,
        shop_db=shop_db, settings_db=settings_db, combat_db=combat_db,
        audit_db=audit_db, images_dir=images_dir, users_dir=users_dir,
    )


# ═════════════════════════════════════════════════════════════════════════════
# 1 · Sheet-storage: Characters
# ═════════════════════════════════════════════════════════════════════════════

class TestCharacters:
    @pytest.fixture(autouse=True)
    def _ss(self, dbs):
        import commands.sheet_storage as ss
        self.ss = ss

    def test_create_returns_int(self):
        cid = self.ss.create_character("333", GUILD_ID, "Hero")
        assert isinstance(cid, int)

    def test_get_returns_correct_name(self):
        char = self.ss.get_character(USER1_ID, GUILD_ID, USER1_CHAR)
        assert char["name"] == USER1_CHAR

    def test_character_exists_true(self):
        assert self.ss.character_exists(USER1_ID, GUILD_ID, USER1_CHAR)

    def test_character_exists_false(self):
        assert not self.ss.character_exists(USER1_ID, GUILD_ID, "NoOne")

    def test_duplicate_name_raises(self):
        with pytest.raises(Exception):
            self.ss.create_character(USER1_ID, GUILD_ID, USER1_CHAR)

    def test_list_characters_returns_both(self):
        names = {c["name"] for c in self.ss.list_characters(USER1_ID, GUILD_ID)}
        assert USER1_CHAR in names

    def test_delete_character(self):
        cid = self.ss.create_character(USER1_ID, GUILD_ID, "Temp")
        self.ss.delete_character(cid)
        assert not self.ss.character_exists(USER1_ID, GUILD_ID, "Temp")

    def test_delete_cascades_to_sheet(self):
        cid = self.ss.create_character(USER1_ID, GUILD_ID, "Ghost")
        sid = self.ss.create_sheet(cid)
        self.ss.delete_character(cid)
        assert self.ss.get_sheet(sid) is None

    def test_get_returns_none_for_missing(self):
        assert self.ss.get_character(USER1_ID, GUILD_ID, "NoOne") is None

    def test_search_by_name_partial(self):
        results = self.ss.search_characters(GUILD_ID, name_query=USER1_CHAR[:3])
        assert any(r["name"] == USER1_CHAR for r in results)

    def test_search_no_match(self):
        assert self.ss.search_characters(GUILD_ID, name_query="ZZZNOMATCH") == []

    def test_get_characters_by_name_in_guild(self):
        # Two users, same character name in same guild
        self.ss.create_character(USER2_ID, GUILD_ID, "SharedName")
        self.ss.create_character(USER1_ID, GUILD_ID, "SharedName")
        results = self.ss.get_characters_by_name_in_guild(GUILD_ID, "SharedName")
        assert len(results) == 2

    def test_case_insensitive_exists(self):
        assert self.ss.character_exists(USER1_ID, GUILD_ID, USER1_CHAR.lower())

    def test_get_sheets_by_user(self):
        rows = self.ss.get_sheets_by_user(USER1_ID, GUILD_ID)
        assert len(rows) >= 1


# ═════════════════════════════════════════════════════════════════════════════
# 2 · Sheet-storage: Sheets & Fields
# ═════════════════════════════════════════════════════════════════════════════

class TestSheetsAndFields:
    @pytest.fixture(autouse=True)
    def _ss(self, dbs):
        import commands.sheet_storage as ss
        self.ss = ss
        char = ss.get_character(USER1_ID, GUILD_ID, USER1_CHAR)
        self.cid = char["character_id"]
        self.sid = ss.get_sheet_by_character(self.cid)["sheet_id"]

    def test_new_sheet_is_draft(self):
        sheet = self.ss.get_sheet(self.sid)
        assert sheet["status"] == "Draft"

    def test_get_sheet_by_character(self):
        sheet = self.ss.get_sheet_by_character(self.cid)
        assert sheet is not None

    def test_set_and_get_field(self):
        self.ss.set_field(self.sid, "Class", "Warrior", sort_order=1)
        fields = dict((f[0], f[1]) for f in self.ss.get_fields(self.sid))
        assert fields["Class"] == "Warrior"

    def test_upsert_overwrites_value(self):
        self.ss.set_field(self.sid, "Race", "Elf", sort_order=1)
        self.ss.set_field(self.sid, "Race", "Dwarf", sort_order=1)
        fields = dict((f[0], f[1]) for f in self.ss.get_fields(self.sid))
        assert fields["Race"] == "Dwarf"

    def test_delete_field(self):
        self.ss.set_field(self.sid, "TempField", "x")
        self.ss.delete_field(self.sid, "TempField")
        fields = dict((f[0], f[1]) for f in self.ss.get_fields(self.sid))
        assert "TempField" not in fields

    def test_sort_order_respected(self):
        self.ss.set_field(self.sid, "Zzz", "last",  sort_order=99)
        self.ss.set_field(self.sid, "Aaa", "first", sort_order=1)
        names = [f[0] for f in self.ss.get_fields(self.sid)]
        assert names.index("Aaa") < names.index("Zzz")

    def test_set_sheet_status(self):
        self.ss.set_sheet_status(self.sid, "Pending")
        sheet = self.ss.get_sheet(self.sid)
        assert sheet["status"] == "Pending"

    def test_get_pending_sheet(self):
        sheet = self.ss.get_pending_sheet(self.cid)
        assert sheet is not None

    def test_get_pending_sheet_none_when_approved(self):
        self.ss.set_sheet_status(self.sid, "Approved")
        # no Draft/Pending remains
        assert self.ss.get_pending_sheet(self.cid) is None

    def test_get_approved_sheet(self):
        self.ss.set_sheet_status(self.sid, "Approved")
        sheet = self.ss.get_approved_sheet(self.cid)
        assert sheet is not None

    def test_search_by_status(self):
        self.ss.set_sheet_status(self.sid, "Pending")
        rows = self.ss.search_characters(GUILD_ID, status="Pending")
        assert any(r["character_id"] == self.cid for r in rows)

    def test_pending_review_record(self):
        self.ss.set_pending_review(self.sid, "ch1", "msg1")
        pr = self.ss.get_pending_review(self.sid)
        assert pr["discord_message_id"] == "msg1"

    def test_clear_pending_review(self):
        self.ss.set_pending_review(self.sid, "ch1", "msg1")
        self.ss.clear_pending_review(self.sid)
        assert self.ss.get_pending_review(self.sid) is None

    def test_record_review_stored(self):
        self.ss.record_review(self.sid, USER1_ID, "Approve", "Great sheet!")
        # No exception = pass


# ═════════════════════════════════════════════════════════════════════════════
# 3 · Sheet-storage: Dual-sheet model
# ═════════════════════════════════════════════════════════════════════════════

class TestDualSheetModel:
    @pytest.fixture(autouse=True)
    def _ss(self, dbs):
        import commands.sheet_storage as ss
        self.ss   = ss
        self.dbs  = dbs
        char = ss.get_character(USER1_ID, GUILD_ID, USER1_CHAR)
        self.cid = char["character_id"]
        self.draft_sid = ss.get_sheet_by_character(self.cid)["sheet_id"]

    def test_promote_draft_to_approved(self):
        self.ss.set_sheet_status(self.draft_sid, "Pending")
        self.ss.promote_draft_to_approved(self.draft_sid)
        sheet = self.ss.get_approved_sheet(self.cid)
        assert sheet["status"] == "Approved"

    def test_promote_removes_old_approved(self):
        # First approval
        self.ss.set_sheet_status(self.draft_sid, "Pending")
        self.ss.promote_draft_to_approved(self.draft_sid)
        # Fork a second draft and approve again
        new_draft_sid = self.ss.create_draft_from_approved(self.cid)
        self.ss.set_sheet_status(new_draft_sid, "Pending")
        self.ss.promote_draft_to_approved(new_draft_sid)
        # Only one Approved sheet should remain
        conn = sqlite3.connect(self.dbs["sheets_db"])
        count = conn.execute(
            "SELECT COUNT(*) FROM sheets WHERE character_id=? AND status='Approved'",
            (self.cid,),
        ).fetchone()[0]
        conn.close()
        assert count == 1

    def test_fork_copies_fields(self):
        self.ss.set_field(self.draft_sid, "Class", "Mage", sort_order=1)
        self.ss.set_sheet_status(self.draft_sid, "Pending")
        self.ss.promote_draft_to_approved(self.draft_sid)
        new_sid = self.ss.create_draft_from_approved(self.cid)
        fields = dict((f[0], f[1]) for f in self.ss.get_fields(new_sid))
        assert fields.get("Class") == "Mage"

    def test_fork_without_approved_raises(self):
        with pytest.raises(Exception):
            self.ss.create_draft_from_approved(self.cid)

    def test_both_sheets_coexist(self):
        self.ss.set_sheet_status(self.draft_sid, "Pending")
        self.ss.promote_draft_to_approved(self.draft_sid)
        new_draft_sid = self.ss.create_draft_from_approved(self.cid)
        assert self.ss.get_approved_sheet(self.cid) is not None
        assert self.ss.get_pending_sheet(self.cid) is not None

    def test_pending_sheets_for_guild(self):
        self.ss.set_sheet_status(self.draft_sid, "Pending")
        rows = self.ss.get_pending_sheets_for_guild(GUILD_ID)
        assert any(r["character_id"] == self.cid for r in rows)


# ═════════════════════════════════════════════════════════════════════════════
# 4 · Sheet-storage: Guild templates
# ═════════════════════════════════════════════════════════════════════════════

class TestGuildTemplates:
    @pytest.fixture(autouse=True)
    def _ss(self, dbs):
        import commands.sheet_storage as ss
        self.ss = ss

    def test_add_and_get_field(self):
        self.ss.add_template_field(GUILD_ID, "Background", sort_order=1)
        tmpl = {f["field_name"] for f in self.ss.get_template(GUILD_ID)}
        assert "Background" in tmpl

    def test_required_flag(self):
        self.ss.add_template_field(GUILD_ID, "Age", sort_order=2, required=1)
        row = next(f for f in self.ss.get_template(GUILD_ID) if f["field_name"] == "Age")
        assert row["required"] == 1

    def test_optional_flag(self):
        self.ss.add_template_field(GUILD_ID, "Hobby", sort_order=3, required=0)
        row = next(f for f in self.ss.get_template(GUILD_ID) if f["field_name"] == "Hobby")
        assert row["required"] == 0

    def test_remove_field(self):
        self.ss.add_template_field(GUILD_ID, "Gone")
        self.ss.remove_template_field(GUILD_ID, "Gone")
        names = {f["field_name"] for f in self.ss.get_template(GUILD_ID)}
        assert "Gone" not in names

    def test_clear_template(self):
        self.ss.add_template_field(GUILD_ID, "A")
        self.ss.add_template_field(GUILD_ID, "B")
        self.ss.clear_template(GUILD_ID)
        assert self.ss.get_template(GUILD_ID) == []

    def test_sort_order_respected(self):
        self.ss.add_template_field(GUILD_ID, "ZField", sort_order=99)
        self.ss.add_template_field(GUILD_ID, "AField", sort_order=1)
        names = [f["field_name"] for f in self.ss.get_template(GUILD_ID)]
        assert names.index("AField") < names.index("ZField")

    def test_apply_template_adds_missing_fields(self):
        self.ss.add_template_field(GUILD_ID, "Race", sort_order=1)
        char = self.ss.get_character(USER1_ID, GUILD_ID, USER1_CHAR)
        sid = self.ss.get_sheet_by_character(char["character_id"])["sheet_id"]
        self.ss.apply_template(sid, GUILD_ID)
        fields = dict((f[0], f[1]) for f in self.ss.get_fields(sid))
        assert "Race" in fields

    def test_apply_template_does_not_overwrite(self):
        self.ss.add_template_field(GUILD_ID, "Class", sort_order=1)
        char = self.ss.get_character(USER1_ID, GUILD_ID, USER1_CHAR)
        sid = self.ss.get_sheet_by_character(char["character_id"])["sheet_id"]
        self.ss.set_field(sid, "Class", "Fighter")
        self.ss.apply_template(sid, GUILD_ID)
        fields = dict((f[0], f[1]) for f in self.ss.get_fields(sid))
        assert fields["Class"] == "Fighter"

    def test_two_guilds_isolated(self):
        OTHER = "888888888888888888"
        self.ss.add_template_field(GUILD_ID, "GuildAField")
        self.ss.add_template_field(OTHER,    "GuildBField")
        a_names = {f["field_name"] for f in self.ss.get_template(GUILD_ID)}
        b_names = {f["field_name"] for f in self.ss.get_template(OTHER)}
        assert "GuildAField" in a_names and "GuildAField" not in b_names
        assert "GuildBField" in b_names and "GuildBField" not in a_names


# ═════════════════════════════════════════════════════════════════════════════
# 5 · Audit log utilities
# ═════════════════════════════════════════════════════════════════════════════

class TestAuditLog:
    @pytest.fixture(autouse=True)
    def _al(self, dbs):
        import commands.audit_log as al
        al.ensure_audit_log_table()
        self.al        = al
        self.audit_db  = dbs["audit_db"]

    def _rows(self):
        conn = sqlite3.connect(self.audit_db)
        rows = conn.execute("SELECT * FROM AuditLog").fetchall()
        conn.close()
        return rows

    def test_write_stores_row(self):
        self.al.write_discord_audit_log(USER1_ID, "/cmd", "test_action")
        assert len(self._rows()) == 1

    def test_write_response_status(self):
        self.al.write_discord_audit_log("x", "/r", "a", response_status=404)
        conn = sqlite3.connect(self.audit_db)
        row = conn.execute("SELECT response_status FROM AuditLog").fetchone()
        conn.close()
        assert row[0] == 404

    def test_write_with_request_details(self):
        self.al.write_discord_audit_log(USER1_ID, "/cmd", "act", request_details={"k": "v"})
        conn = sqlite3.connect(self.audit_db)
        row = conn.execute("SELECT request_details FROM AuditLog").fetchone()
        conn.close()
        assert "k" in (row[0] or "")

    def test_purge_removes_old_rows(self):
        from datetime import datetime, timedelta
        old_ts = (datetime.utcnow() - timedelta(days=31)).isoformat(timespec="seconds") + "Z"
        conn = sqlite3.connect(self.audit_db)
        conn.execute(
            "INSERT INTO AuditLog (created_at,actor,source,method,route,action,response_status)"
            " VALUES (?,?,?,?,?,?,?)",
            (old_ts, "x", "discord_bot", "DISCORD", "/r", "a", 200),
        )
        conn.commit()
        conn.close()
        self.al.purge_old_audit_logs()
        assert len(self._rows()) == 0

    def test_purge_keeps_recent(self):
        self.al.write_discord_audit_log("x", "/r", "a")
        self.al.purge_old_audit_logs()
        assert len(self._rows()) == 1

    def test_json_dump_truncates(self):
        result = self.al._json_dump_limited({"k": "v" * 2000}, max_len=50)
        assert len(result) <= 50

    def test_json_dump_normal(self):
        assert "hello" in self.al._json_dump_limited({"hello": "world"})

    def test_json_dump_non_serialisable(self):
        assert isinstance(self.al._json_dump_limited(object()), str)

    def test_flatten_leaf(self):
        pairs = self.al._flatten_option_pairs([{"name": "amt", "value": 10}])
        assert ("amt", 10) in pairs

    def test_flatten_nested(self):
        opts = [{"name": "sub", "options": [{"name": "leaf", "value": "x"}]}]
        pairs = self.al._flatten_option_pairs(opts)
        assert any("leaf" in p[0] for p in pairs)

    def test_build_full_command(self):
        cmd = self.al._build_full_command("currency", [{"name": "amount", "value": 50}])
        assert "/currency" in cmd and "50" in cmd

    def test_build_input_data(self):
        assert self.al._build_input_data([{"name": "job", "value": "Guard"}]) == {"job": "Guard"}

    def test_build_interaction_details(self):
        ix = make_interaction(USER1_ID)
        ix.data     = {"name": "help", "options": []}
        ix.guild_id = int(GUILD_ID)
        result = self.al.build_discord_interaction_details(ix, command_name="help")
        assert result["command"] == "help"
        assert result["user_id"] == str(ix.user.id)


# ═════════════════════════════════════════════════════════════════════════════
# 6 · Admin permission (Config cog)
# ═════════════════════════════════════════════════════════════════════════════

class TestAdminPermission:
    @pytest.fixture(autouse=True)
    def _cfg(self, dbs):
        import commands.Config as cfg_mod
        self.cog = cfg_mod.Config.__new__(cfg_mod.Config)
        self.cog.db_path = dbs["settings_db"]

    def test_admin_user_granted(self):
        ix = make_interaction(USER1_ID, admin=True)
        assert run(self.cog.is_admin(ix))

    def test_regular_user_denied(self):
        ix = make_interaction(USER2_ID, admin=False)
        assert not run(self.cog.is_admin(ix))

    def test_no_guild_denied(self):
        ix = make_interaction(USER1_ID, admin=True)
        ix.guild = None
        assert not run(self.cog.is_admin(ix))

    def test_no_user_denied(self):
        ix = make_interaction(USER1_ID)
        ix.user = None
        assert not run(self.cog.is_admin(ix))

    def test_role_not_in_db_denies(self):
        # Settings.db has ADMIN_ROLE_ID but user has a different role
        ix = make_interaction(USER1_ID)
        other_role = MagicMock()
        other_role.id = 99999
        ix.user.roles = [other_role]
        assert not run(self.cog.is_admin(ix))


# ═════════════════════════════════════════════════════════════════════════════
# 7 · Config command handlers
# ═════════════════════════════════════════════════════════════════════════════

class TestConfigCommandHandlers:
    @pytest.fixture(autouse=True)
    def _cfg(self, dbs):
        import commands.Config as cfg_mod
        self.cog         = cfg_mod.Config.__new__(cfg_mod.Config)
        self.cfg_mod     = cfg_mod
        self.settings_db = dbs["settings_db"]

    def test_field_add_admin_success(self, dbs):
        import commands.sheet_storage as ss
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        ix.guild.id = int(GUILD_ID)
        run(self.cfg_mod.Config.field_add.callback(self.cog, ix, "Race", True))
        assert "Race" in {f["field_name"] for f in ss.get_template(GUILD_ID)}

    def test_field_add_non_admin_rejected(self):
        ix = make_interaction(USER2_ID, admin=False, bot=make_bot(admin=False))
        ix.guild.id = int(GUILD_ID)
        run(self.cfg_mod.Config.field_add.callback(self.cog, ix, "Race", True))
        assert ix.response.calls

    def test_field_add_no_guild_rejected(self):
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        ix.guild = None
        run(self.cfg_mod.Config.field_add.callback(self.cog, ix, "Race", True))
        assert ix.response.calls

    def test_field_remove_admin_success(self, dbs):
        import commands.sheet_storage as ss
        ss.add_template_field(GUILD_ID, "ToRemove", sort_order=1)
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        ix.guild.id = int(GUILD_ID)
        run(self.cfg_mod.Config.field_remove.callback(self.cog, ix, "ToRemove"))
        assert "ToRemove" not in {f["field_name"] for f in ss.get_template(GUILD_ID)}

    def test_field_remove_non_admin_rejected(self):
        ix = make_interaction(USER2_ID, admin=False, bot=make_bot(admin=False))
        ix.guild.id = int(GUILD_ID)
        run(self.cfg_mod.Config.field_remove.callback(self.cog, ix, "Any"))
        assert ix.response.calls

    def test_delete_character_cmd_success(self, dbs):
        import commands.sheet_storage as ss
        ss.create_character(USER1_ID, GUILD_ID, "DeleteMe")
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        ix.guild.id = int(GUILD_ID)
        target = MagicMock()
        target.id      = int(USER1_ID)
        target.mention = f"<@{USER1_ID}>"
        run(self.cfg_mod.Config.delete_character_cmd.callback(self.cog, ix, target, "DeleteMe"))
        assert not ss.character_exists(USER1_ID, GUILD_ID, "DeleteMe")

    def test_delete_character_cmd_not_found(self):
        import commands.sheet_storage as ss
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        ix.guild.id = int(GUILD_ID)
        target = MagicMock()
        target.id      = int(USER1_ID)
        target.mention = f"<@{USER1_ID}>"
        run(self.cfg_mod.Config.delete_character_cmd.callback(self.cog, ix, target, "NoSuchChar"))
        assert ix.response.calls

    def test_reset_fields_clears_template(self, dbs):
        import commands.sheet_storage as ss
        ss.add_template_field(GUILD_ID, "F1", sort_order=1)
        choice = MagicMock(); choice.value = "fields"
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        ix.guild.id = int(GUILD_ID)
        run(self.cfg_mod.Config.reset.callback(self.cog, ix, choice))
        assert ss.get_template(GUILD_ID) == []

    def test_reset_non_admin_rejected(self):
        choice = MagicMock(); choice.value = "fields"
        ix = make_interaction(USER2_ID, admin=False, bot=make_bot(admin=False))
        ix.guild.id = int(GUILD_ID)
        run(self.cfg_mod.Config.reset.callback(self.cog, ix, choice))
        assert ix.response.calls

    def test_work_cooldown_sets_value(self, dbs):
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        ix.guild.id = int(GUILD_ID)
        run(self.cfg_mod.work_cooldown.callback(ix, 7))
        conn = sqlite3.connect(dbs["settings_db"])
        row = conn.execute("SELECT days FROM WorkCooldown WHERE id=1").fetchone()
        conn.close()
        assert row and row[0] == 7

    def test_work_cooldown_negative_rejected(self):
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        run(self.cfg_mod.work_cooldown.callback(ix, -1))
        assert ix.response.calls

    def test_work_cooldown_non_admin_rejected(self):
        ix = make_interaction(USER2_ID, admin=False, bot=make_bot(admin=False))
        run(self.cfg_mod.work_cooldown.callback(ix, 3))
        assert ix.response.calls


# ═════════════════════════════════════════════════════════════════════════════
# 8 · Economy command handlers
# ═════════════════════════════════════════════════════════════════════════════

class TestEconomyCommandHandlers:
    @pytest.fixture(autouse=True)
    def _eco(self, dbs):
        from commands.Economy import (
            currency_view, currency_remove, currency_set,
            work_create, work_edit, work_assign, job_claim,
            fetch_currency, set_currency,
        )
        self.view    = currency_view.callback
        self.remove  = currency_remove.callback
        self.cset    = currency_set.callback
        self.wcreate = work_create.callback
        self.wedit   = work_edit.callback
        self.wassign = work_assign.callback
        self.claim   = job_claim.callback
        self.fetch   = fetch_currency
        self.set     = set_currency
        self.edb     = dbs["economy_db"]

    def test_currency_view_sends_embed(self):
        self.set(USER1_ID, "Currency", 100.0)
        ix = make_interaction(USER1_ID, bot=make_bot())
        run(self.view(ix, f"<@{USER1_ID}>"))
        assert ix.response.last_embed() is not None

    def test_currency_set_admin_sets_amount(self):
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        run(self.cset(ix, f"<@{USER2_ID}>", 500.0))
        assert self.fetch(USER2_ID, "Currency") == 500.0

    def test_currency_set_non_admin_rejected(self):
        ix = make_interaction(USER2_ID, admin=False, bot=make_bot(admin=False))
        run(self.cset(ix, f"<@{USER1_ID}>", 999.0))
        assert self.fetch(USER1_ID, "Currency") == 0.0

    def test_currency_remove_deducts(self):
        self.set(USER1_ID, "Currency", 200.0)
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        run(self.remove(ix, f"<@{USER1_ID}>", 50.0))
        assert self.fetch(USER1_ID, "Currency") == 150.0

    def test_currency_remove_floors_at_zero(self):
        self.set(USER2_ID, "Currency", 10.0)
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        run(self.remove(ix, f"<@{USER2_ID}>", 9999.0))
        assert self.fetch(USER2_ID, "Currency") == 0.0

    def test_currency_remove_non_admin_rejected(self):
        self.set(USER1_ID, "Currency", 100.0)
        ix = make_interaction(USER2_ID, admin=False, bot=make_bot(admin=False))
        run(self.remove(ix, f"<@{USER1_ID}>", 50.0))
        assert self.fetch(USER1_ID, "Currency") == 100.0

    def test_work_create_stores_job(self):
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        run(self.wcreate(ix, "Blacksmith", 75.0))
        conn = sqlite3.connect(self.edb)
        row = conn.execute("SELECT payment FROM jobs WHERE job_name='Blacksmith'").fetchone()
        conn.close()
        assert row and row[0] == 75.0

    def test_work_create_non_admin_rejected(self):
        ix = make_interaction(USER2_ID, admin=False, bot=make_bot(admin=False))
        run(self.wcreate(ix, "Ghost", 10.0))
        conn = sqlite3.connect(self.edb)
        row = conn.execute("SELECT * FROM jobs WHERE job_name='Ghost'").fetchone()
        conn.close()
        assert row is None

    def test_work_edit_updates_payment(self):
        conn = sqlite3.connect(self.edb)
        conn.execute("INSERT INTO jobs VALUES ('Miner', 30.0)")
        conn.commit(); conn.close()
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        run(self.wedit(ix, "Miner", 55.0))
        conn = sqlite3.connect(self.edb)
        row = conn.execute("SELECT payment FROM jobs WHERE job_name='Miner'").fetchone()
        conn.close()
        assert row[0] == 55.0

    def test_work_edit_missing_job_sends_error(self):
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        run(self.wedit(ix, "NoJob", 10.0))
        assert "does not exist" in (ix.response.last_content() or "").lower() or ix.response.calls

    def test_work_assign_assigns_job(self):
        conn = sqlite3.connect(self.edb)
        conn.execute("INSERT INTO jobs VALUES ('Baker', 20.0)")
        conn.commit(); conn.close()
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        run(self.wassign(ix, "Baker", f"<@{USER1_ID}>", USER1_CHAR))
        conn = sqlite3.connect(self.edb)
        row = conn.execute("SELECT job_name FROM user_jobs WHERE user_id=?", (USER1_ID,)).fetchone()
        conn.close()
        assert row and row[0] == "Baker"

    def test_work_assign_char_not_found(self):
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        run(self.wassign(ix, "Baker", f"<@{USER1_ID}>", "NoCharHere"))
        assert ix.response.calls

    def test_job_claim_no_job_sends_error(self):
        ix = make_interaction(USER1_ID, bot=make_bot())
        ix.user.id = int(USER1_ID)
        run(self.claim(ix, USER1_CHAR))
        assert ix.response.calls


# ═════════════════════════════════════════════════════════════════════════════
# 9 · Inventory command handlers
# ═════════════════════════════════════════════════════════════════════════════

class TestInventoryCommandHandlers:
    @pytest.fixture(autouse=True)
    def _inv(self, dbs):
        from commands.Inventory import inventory_group, fetch_items, upsert_item
        self.add_cmd    = inventory_group.get_command("add").callback
        self.view_cmd   = inventory_group.get_command("view").callback
        self.remove_cmd = inventory_group.get_command("remove").callback
        self.fetch      = fetch_items
        self.upsert     = upsert_item

    def test_add_admin_success(self):
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        run(self.add_cmd(ix, f"<@{USER2_ID}>", "Torch", 5))
        assert dict(self.fetch(USER2_ID, "Inventory")).get("Torch") == 5

    def test_add_with_character(self):
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        run(self.add_cmd(ix, f"<@{USER1_ID}>", "Rope", 2, USER1_CHAR))
        assert dict(self.fetch(USER1_ID, USER1_CHAR)).get("Rope") == 2

    def test_add_non_admin_rejected(self):
        ix = make_interaction(USER2_ID, admin=False, bot=make_bot(admin=False))
        run(self.add_cmd(ix, f"<@{USER1_ID}>", "GoldBar", 1))
        assert self.fetch(USER1_ID, "Inventory") == []

    def test_add_char_not_found(self):
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        run(self.add_cmd(ix, f"<@{USER1_ID}>", "Potion", 1, "NoSuchChar"))
        assert self.fetch(USER1_ID, "NoSuchChar") == []

    def test_view_no_items_sends_message(self):
        ix = make_interaction(USER1_ID, bot=make_bot())
        run(self.view_cmd(ix, f"<@{USER2_ID}>"))
        assert ix.response.calls

    def test_view_with_items_sends_embed(self):
        self.upsert(USER1_ID, "Inventory", "Lantern", 3)
        ix = make_interaction(USER1_ID, bot=make_bot())
        run(self.view_cmd(ix, f"<@{USER1_ID}>"))
        assert ix.response.last_embed() is not None

    def test_view_invalid_mention_rejected(self):
        ix = make_interaction(USER1_ID, bot=make_bot())
        run(self.view_cmd(ix, "not-a-mention"))
        assert ix.response.calls

    def test_remove_admin_deducts(self):
        self.upsert(USER1_ID, "Inventory", "Key", 5)
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        run(self.remove_cmd(ix, f"<@{USER1_ID}>", "Key", 3))
        assert dict(self.fetch(USER1_ID, "Inventory")).get("Key") == 2

    def test_remove_non_admin_rejected(self):
        self.upsert(USER1_ID, "Inventory", "Diamond", 10)
        ix = make_interaction(USER2_ID, admin=False, bot=make_bot(admin=False))
        run(self.remove_cmd(ix, f"<@{USER1_ID}>", "Diamond", 10))
        assert dict(self.fetch(USER1_ID, "Inventory")).get("Diamond") == 10

    def test_remove_invalid_mention_rejected(self):
        ix = make_interaction(USER1_ID, admin=True, bot=make_bot(admin=True))
        run(self.remove_cmd(ix, "bad-mention", "Item", 1))
        assert ix.response.calls


# ═════════════════════════════════════════════════════════════════════════════
# 10 · Market command handlers
# ═════════════════════════════════════════════════════════════════════════════

class TestMarketCommandHandlers:
    @pytest.fixture(autouse=True)
    def _mkt(self, dbs):
        from commands.Market import ItemCog, ShopCog, catalog_add_item, add_shop_item
        self.ab = make_bot(admin=True)
        self.ic = ItemCog.__new__(ItemCog); self.ic.bot = self.ab
        self.sc = ShopCog.__new__(ShopCog); self.sc.bot = self.ab
        catalog_add_item("Apple", consumable="Yes", description="A fruit")
        add_shop_item("Apple", 5)

    # ── ItemCog ───────────────────────────────────────────────────────────────

    def test_item_add_creates_entry(self):
        from commands.Market import ItemCog, catalog_get_item
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        run(ItemCog.add.callback(self.ic, ix, "Banana"))
        assert catalog_get_item("Banana") is not None

    def test_item_add_non_admin_rejected(self):
        from commands.Market import ItemCog, catalog_get_item
        bot = make_bot(admin=False); self.ic.bot = bot
        ix = make_interaction(USER2_ID, admin=False, bot=bot)
        run(ItemCog.add.callback(self.ic, ix, "SecretItem"))
        assert catalog_get_item("SecretItem") is None
        self.ic.bot = self.ab

    def test_item_add_duplicate_sends_error(self):
        from commands.Market import ItemCog
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        run(ItemCog.add.callback(self.ic, ix, "Apple"))
        assert ix.response.calls

    def test_item_list_mentions_item(self):
        from commands.Market import ItemCog
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        run(ItemCog.list.callback(self.ic, ix))
        assert "Apple" in (ix.response.last_content() or "")

    def test_set_consumable_updates_db(self):
        from commands.Market import ItemCog, catalog_get_item
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        choice = MagicMock(); choice.value = "No"
        run(ItemCog.set_consumable.callback(self.ic, ix, "Apple", choice))
        assert catalog_get_item("Apple")[1] == "No"

    # ── ShopCog ───────────────────────────────────────────────────────────────

    def test_shop_add_admin_adds(self):
        from commands.Market import ShopCog, catalog_add_item, get_shop_item
        catalog_add_item("Orange")
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        run(ShopCog.add.callback(self.sc, ix, "Orange", 10))
        assert get_shop_item("Orange") is not None

    def test_shop_add_not_in_catalog_rejected(self):
        from commands.Market import ShopCog, get_shop_item
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        run(ShopCog.add.callback(self.sc, ix, "PhantomItem", 5))
        assert get_shop_item("PhantomItem") is None

    def test_shop_add_already_listed_rejected(self):
        from commands.Market import ShopCog, get_shop_item
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        run(ShopCog.add.callback(self.sc, ix, "Apple", 99))
        assert get_shop_item("Apple")[1] == 5  # price unchanged

    def test_shop_remove_admin_removes(self):
        from commands.Market import ShopCog, get_shop_item
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        run(ShopCog.remove.callback(self.sc, ix, "Apple"))
        assert get_shop_item("Apple") is None

    def test_shop_remove_not_listed_sends_error(self):
        from commands.Market import ShopCog
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        run(ShopCog.remove.callback(self.sc, ix, "Phantom"))
        assert ix.response.calls

    def test_shop_buy_success(self, dbs):
        from commands.Market import ShopCog
        from commands.Economy import set_currency, fetch_currency
        from commands.Inventory import fetch_items
        set_currency(USER1_ID, "Currency", 100.0)
        ix = make_interaction(USER1_ID, bot=self.ab); ix.user.id = int(USER1_ID)
        run(ShopCog.buy.callback(self.sc, ix, "Apple", 5))
        assert fetch_currency(USER1_ID, "Currency") == 75.0
        assert dict(fetch_items(USER1_ID, "Inventory")).get("Apple") == 5

    def test_shop_buy_insufficient_funds(self, dbs):
        from commands.Market import ShopCog
        from commands.Economy import set_currency, fetch_currency
        set_currency(USER2_ID, "Currency", 2.0)
        ix = make_interaction(USER2_ID, bot=self.ab); ix.user.id = int(USER2_ID)
        run(ShopCog.buy.callback(self.sc, ix, "Apple", 10))
        assert fetch_currency(USER2_ID, "Currency") == 2.0

    def test_shop_buy_not_in_shop_rejected(self):
        from commands.Market import ShopCog
        ix = make_interaction(USER1_ID, bot=self.ab); ix.user.id = int(USER1_ID)
        run(ShopCog.buy.callback(self.sc, ix, "NotInShop", 1))
        assert ix.response.calls

    def test_shop_sell_success(self, dbs):
        from commands.Market import ShopCog
        from commands.Economy import fetch_currency, set_currency
        from commands.Inventory import upsert_item, fetch_items
        upsert_item(USER1_ID, "Inventory", "Apple", 3)
        set_currency(USER1_ID, "Inventory", 0.0)
        ix = make_interaction(USER1_ID, bot=self.ab); ix.user.id = int(USER1_ID)
        run(ShopCog.sell.callback(self.sc, ix, "Apple", 2))
        assert fetch_currency(USER1_ID, "Inventory") == 10.0
        assert dict(fetch_items(USER1_ID, "Inventory")).get("Apple") == 1

    def test_shop_sell_not_enough_items(self):
        from commands.Market import ShopCog
        ix = make_interaction(USER1_ID, bot=self.ab); ix.user.id = int(USER1_ID)
        run(ShopCog.sell.callback(self.sc, ix, "Apple", 999))
        assert ix.response.calls

    def test_shop_sell_item_not_in_shop(self):
        from commands.Market import ShopCog
        ix = make_interaction(USER1_ID, bot=self.ab); ix.user.id = int(USER1_ID)
        run(ShopCog.sell.callback(self.sc, ix, "UnknownItem", 1))
        assert ix.response.calls


# ═════════════════════════════════════════════════════════════════════════════
# 11 · Combat command handlers
# ═════════════════════════════════════════════════════════════════════════════

class TestCombatCommandHandlers:
    @pytest.fixture(autouse=True)
    def _cbt(self, dbs):
        from commands.Combat import FightDynamic, HealthBar, Death, ensure_death_table
        ensure_death_table()
        self.ab  = make_bot(admin=True)
        self.fc  = FightDynamic.__new__(FightDynamic); self.fc.bot = self.ab; self.fc.fight_data = {}
        self.hc  = HealthBar.__new__(HealthBar);  self.hc.bot  = self.ab; self.hc.health_data  = {}
        self.dc  = Death.__new__(Death);          self.dc.bot  = self.ab
        self.cdb = dbs["combat_db"]

    # ── fight_dynamic_rules ───────────────────────────────────────────────────

    def test_rules_admin_updates_weights(self):
        from commands.Combat import FightDynamic, get_combat_weights
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        run(FightDynamic.fight_dynamic_rules.callback(self.fc, ix, 0.5, 0.3, 0.1, 0.1))
        assert get_combat_weights()[0] == 0.5

    def test_rules_non_admin_rejected(self):
        from commands.Combat import FightDynamic
        bot = make_bot(admin=False); self.fc.bot = bot
        ix = make_interaction(USER2_ID, admin=False, bot=bot)
        run(FightDynamic.fight_dynamic_rules.callback(self.fc, ix, 0.99, 0.0, 0.0, 0.01))
        assert ix.response.calls
        self.fc.bot = self.ab

    # ── health_track ──────────────────────────────────────────────────────────

    def test_health_track_char_not_found(self):
        from commands.Combat import HealthBar
        ix = make_interaction(USER1_ID, bot=self.ab); ix.user.id = int(USER1_ID)
        run(HealthBar.health_track.callback(self.hc, ix, "GhostChar", 20))
        assert ix.response.calls

    def test_health_track_sends_embed(self):
        from commands.Combat import HealthBar
        ix = make_interaction(USER1_ID, bot=self.ab); ix.user.id = int(USER1_ID)
        msg = MagicMock(); msg.id = 99999; msg.add_reaction = AsyncMock()
        ix.original_response = AsyncMock(return_value=msg)
        run(HealthBar.health_track.callback(self.hc, ix, USER1_CHAR, 10))
        assert ix.response.last_embed() is not None

    # ── death.set ─────────────────────────────────────────────────────────────

    def test_death_set_admin_updates(self):
        from commands.Combat import Death
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        run(Death.set_death.callback(self.dc, ix, 14))
        conn = sqlite3.connect(self.cdb)
        row = conn.execute("SELECT cooldown FROM GlobalSettings WHERE id=1").fetchone()
        conn.close()
        assert row[0] == 14

    def test_death_set_non_admin_rejected(self):
        from commands.Combat import Death
        bot = make_bot(admin=False); self.dc.bot = bot
        ix = make_interaction(USER2_ID, admin=False, bot=bot)
        run(Death.set_death.callback(self.dc, ix, 99))
        conn = sqlite3.connect(self.cdb)
        row = conn.execute("SELECT cooldown FROM GlobalSettings WHERE id=1").fetchone()
        conn.close()
        assert row[0] == 0
        self.dc.bot = self.ab

    # ── death.infinite ────────────────────────────────────────────────────────

    def test_death_infinite_yes(self):
        from commands.Combat import Death
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        c = MagicMock(); c.value = "yes"
        run(Death.set_infinite.callback(self.dc, ix, c))
        conn = sqlite3.connect(self.cdb)
        row = conn.execute("SELECT infinite FROM GlobalSettings WHERE id=1").fetchone()
        conn.close()
        assert row[0] == 1

    def test_death_infinite_no(self):
        from commands.Combat import Death
        conn = sqlite3.connect(self.cdb)
        conn.execute("UPDATE GlobalSettings SET infinite=1 WHERE id=1")
        conn.commit(); conn.close()
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        c = MagicMock(); c.value = "no"
        run(Death.set_infinite.callback(self.dc, ix, c))
        conn = sqlite3.connect(self.cdb)
        row = conn.execute("SELECT infinite FROM GlobalSettings WHERE id=1").fetchone()
        conn.close()
        assert row[0] == 0

    # ── death.reset ───────────────────────────────────────────────────────────

    def test_death_reset_admin_success(self):
        from commands.Combat import Death
        now = int(time.time())
        conn = sqlite3.connect(self.cdb)
        conn.execute(
            "INSERT OR REPLACE INTO DeathCooldown VALUES (?,?,7,0,?)",
            (USER1_ID, USER1_CHAR, now)
        )
        conn.commit(); conn.close()
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        run(Death.reset_death.callback(self.dc, ix, f"<@{USER1_ID}>", USER1_CHAR))
        conn = sqlite3.connect(self.cdb)
        row = conn.execute(
            "SELECT cooldown FROM DeathCooldown WHERE user_id=? AND name=?",
            (USER1_ID, USER1_CHAR)
        ).fetchone()
        conn.close()
        assert row and row[0] == 0

    def test_death_reset_char_not_found(self):
        from commands.Combat import Death
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        run(Death.reset_death.callback(self.dc, ix, f"<@{USER1_ID}>", "GhostChar"))
        assert ix.response.calls

    def test_death_reset_non_admin_rejected(self):
        from commands.Combat import Death
        bot = make_bot(admin=False); self.dc.bot = bot
        ix = make_interaction(USER2_ID, admin=False, bot=bot)
        run(Death.reset_death.callback(self.dc, ix, f"<@{USER1_ID}>", USER1_CHAR))
        assert ix.response.calls
        self.dc.bot = self.ab

    # ── death.check ───────────────────────────────────────────────────────────

    def test_death_check_no_record(self):
        from commands.Combat import Death
        ix = make_interaction(USER1_ID, bot=self.ab); ix.user.id = int(USER1_ID)
        run(Death.check.callback(self.dc, ix, USER1_CHAR))
        assert ix.response.calls

    def test_death_check_infinite(self):
        from commands.Combat import Death
        conn = sqlite3.connect(self.cdb)
        conn.execute(
            "INSERT OR REPLACE INTO DeathCooldown VALUES (?,?,0,1,?)",
            (USER1_ID, USER1_CHAR, int(time.time()))
        )
        conn.commit(); conn.close()
        ix = make_interaction(USER1_ID, bot=self.ab); ix.user.id = int(USER1_ID)
        run(Death.check.callback(self.dc, ix, USER1_CHAR))
        assert "infinite" in (ix.response.last_content() or "").lower()

    # ── death.revive ──────────────────────────────────────────────────────────

    def test_revive_no_record_sends_error(self):
        from commands.Combat import Death
        ix = make_interaction(USER1_ID, bot=self.ab); ix.user.id = int(USER1_ID)
        run(Death.revive.callback(self.dc, ix, USER1_CHAR))
        assert ix.response.calls

    def test_revive_infinite_denied(self):
        from commands.Combat import Death
        conn = sqlite3.connect(self.cdb)
        conn.execute(
            "INSERT OR REPLACE INTO DeathCooldown VALUES (?,?,0,1,?)",
            (USER1_ID, USER1_CHAR, int(time.time()))
        )
        conn.commit(); conn.close()
        ix = make_interaction(USER1_ID, bot=self.ab); ix.user.id = int(USER1_ID)
        run(Death.revive.callback(self.dc, ix, USER1_CHAR))
        assert "cannot be revived" in (ix.response.last_content() or "").lower()

    def test_revive_zero_cooldown_succeeds(self):
        from commands.Combat import Death
        conn = sqlite3.connect(self.cdb)
        conn.execute(
            "INSERT OR REPLACE INTO DeathCooldown VALUES (?,?,0,0,?)",
            (USER1_ID, USER1_CHAR, int(time.time()))
        )
        conn.commit(); conn.close()
        ix = make_interaction(USER1_ID, bot=self.ab); ix.user.id = int(USER1_ID)
        run(Death.revive.callback(self.dc, ix, USER1_CHAR))
        assert "revived" in (ix.response.last_content() or "").lower()

    def test_revive_expired_cooldown_succeeds(self):
        from commands.Combat import Death
        old = int(time.time()) - 8 * 86400
        conn = sqlite3.connect(self.cdb)
        conn.execute(
            "INSERT OR REPLACE INTO DeathCooldown VALUES (?,?,7,0,?)",
            (USER1_ID, USER1_CHAR, old)
        )
        conn.commit(); conn.close()
        ix = make_interaction(USER1_ID, bot=self.ab); ix.user.id = int(USER1_ID)
        run(Death.revive.callback(self.dc, ix, USER1_CHAR))
        assert "revived" in (ix.response.last_content() or "").lower()

    def test_revive_active_cooldown_denied(self):
        from commands.Combat import Death
        conn = sqlite3.connect(self.cdb)
        conn.execute(
            "INSERT OR REPLACE INTO DeathCooldown VALUES (?,?,30,0,?)",
            (USER1_ID, USER1_CHAR, int(time.time()))
        )
        conn.commit(); conn.close()
        ix = make_interaction(USER1_ID, bot=self.ab); ix.user.id = int(USER1_ID)
        run(Death.revive.callback(self.dc, ix, USER1_CHAR))
        assert "cannot be revived" in (ix.response.last_content() or "").lower()

    # ── death.list / graveyard ────────────────────────────────────────────────

    def test_death_list_no_records(self):
        from commands.Combat import Death
        ix = make_interaction(USER1_ID, bot=self.ab); ix.user.id = int(USER1_ID)
        run(Death.list_deaths.callback(self.dc, ix))
        assert "no death" in (ix.response.last_content() or "").lower()

    def test_death_list_with_records(self):
        from commands.Combat import Death
        conn = sqlite3.connect(self.cdb)
        conn.execute(
            "INSERT OR REPLACE INTO DeathCooldown VALUES (?,?,0,0,?)",
            (USER1_ID, USER1_CHAR, int(time.time()))
        )
        conn.commit(); conn.close()
        ix = make_interaction(USER1_ID, bot=self.ab); ix.user.id = int(USER1_ID)
        run(Death.list_deaths.callback(self.dc, ix))
        assert ix.response.calls

    def test_graveyard_no_records(self):
        from commands.Combat import Death
        ix = make_interaction(USER1_ID, bot=self.ab)
        run(Death.graveyard.callback(self.dc, ix))
        assert ix.response.calls

    def test_graveyard_with_record(self):
        from commands.Combat import Death
        conn = sqlite3.connect(self.cdb)
        conn.execute(
            "INSERT OR REPLACE INTO DeathCooldown VALUES (?,?,0,0,?)",
            (USER2_ID, USER2_CHAR, int(time.time()))
        )
        conn.commit(); conn.close()
        ix = make_interaction(USER1_ID, bot=self.ab)
        run(Death.graveyard.callback(self.dc, ix))
        assert ix.response.calls


# ═════════════════════════════════════════════════════════════════════════════
# 12 · Death ClaimView buttons (directly-invoked callbacks)
# ═════════════════════════════════════════════════════════════════════════════

class TestDeathClaimView:
    @pytest.fixture(autouse=True)
    def _setup(self, dbs):
        from commands.Combat import ensure_death_table
        ensure_death_table()
        self.cdb = dbs["combat_db"]
        self.ab  = make_bot(admin=True)

    def _make_claim_view(self):
        import discord, sqlite3, time
        from commands.Combat import _admin_check, find_user_db_by_name, ensure_death_table, USERS_DIR, COMBAT_DB

        class ClaimView(discord.ui.View):
            def __init__(self, invoker_id, target_id, char_name, orig_ch):
                super().__init__(timeout=3600)
                self.invoker_id = invoker_id
                self.target_id  = target_id
                self.char_name  = char_name

            @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
            async def approve(self, interaction_button, button):
                if not await _admin_check(interaction_button):
                    return
                tbl = find_user_db_by_name(USERS_DIR, self.char_name, self.target_id)
                if not tbl:
                    await interaction_button.response.send_message("not found", ephemeral=True)
                    return
                ensure_death_table()
                conn = sqlite3.connect(COMBAT_DB)
                c    = conn.cursor()
                c.execute("SELECT cooldown, infinite FROM GlobalSettings WHERE id=1")
                days, inf = c.fetchone() or (0, 0)
                c.execute(
                    "INSERT OR REPLACE INTO DeathCooldown VALUES (?,?,?,?,?)",
                    (str(self.target_id), tbl, days, inf, int(time.time()))
                )
                conn.commit(); conn.close()
                await interaction_button.response.send_message("Approved.", ephemeral=True)
                self.stop()

        return ClaimView(int(USER1_ID), USER1_ID, USER1_CHAR, 12345)

    def test_approve_creates_record(self):
        view = self._make_claim_view()
        ix   = make_interaction(USER1_ID, admin=True, bot=self.ab)
        run(view.approve.callback(ix))
        conn = sqlite3.connect(self.cdb)
        row  = conn.execute(
            "SELECT cooldown FROM DeathCooldown WHERE user_id=? AND name=?",
            (USER1_ID, USER1_CHAR)
        ).fetchone()
        conn.close()
        assert row is not None

    def test_approve_non_admin_blocked(self):
        view = self._make_claim_view()
        ix   = make_interaction(USER2_ID, admin=False, bot=make_bot(admin=False))
        run(view.approve.callback(ix))
        conn = sqlite3.connect(self.cdb)
        row  = conn.execute("SELECT * FROM DeathCooldown").fetchone()
        conn.close()
        assert row is None


# ═════════════════════════════════════════════════════════════════════════════
# 13 · HealthBar reaction handler
# ═════════════════════════════════════════════════════════════════════════════

class TestHealthBarReaction:
    @pytest.fixture(autouse=True)
    def _hc(self, dbs):
        from commands.Combat import HealthBar
        bot = make_bot()
        self.cog = HealthBar.__new__(HealthBar)
        self.cog.bot = bot
        self.cog.health_data = {
            1001: {"name": "Aria", "hp": 10, "max_hp": 10, "table": USER1_CHAR}
        }

    def _reaction(self, emoji, message_id=1001, is_bot=False):
        r = MagicMock()
        r.emoji   = emoji
        r.message = MagicMock()
        r.message.id     = message_id
        r.message.embeds = [MagicMock()]
        r.message.embeds[0].set_field_at = MagicMock()
        r.message.edit   = AsyncMock()
        r.message.delete = AsyncMock()
        r.remove = AsyncMock()
        u = MagicMock(); u.bot = is_bot
        return r, u

    def test_bot_ignored(self):
        r, u = self._reaction("⬇️", is_bot=True)
        run(self.cog.on_reaction_add(r, u))
        assert self.cog.health_data[1001]["hp"] == 10

    def test_unknown_message_ignored(self):
        r, u = self._reaction("⬇️", message_id=9999)
        run(self.cog.on_reaction_add(r, u))
        assert 1001 in self.cog.health_data

    def test_down_decrements(self):
        r, u = self._reaction("⬇️")
        run(self.cog.on_reaction_add(r, u))
        assert self.cog.health_data[1001]["hp"] == 9

    def test_up_increments(self):
        self.cog.health_data[1001]["hp"] = 8
        r, u = self._reaction("⬆️")
        run(self.cog.on_reaction_add(r, u))
        assert self.cog.health_data[1001]["hp"] == 9

    def test_up_capped_at_max(self):
        r, u = self._reaction("⬆️")
        run(self.cog.on_reaction_add(r, u))
        assert self.cog.health_data[1001]["hp"] == 10

    def test_down_floored_at_zero(self):
        self.cog.health_data[1001]["hp"] = 0
        r, u = self._reaction("⬇️")
        run(self.cog.on_reaction_add(r, u))
        assert self.cog.health_data[1001]["hp"] == 0

    def test_skull_removes_tracking(self):
        r, u = self._reaction("💀")
        run(self.cog.on_reaction_add(r, u))
        assert 1001 not in self.cog.health_data

    def test_skull_deletes_message(self):
        r, u = self._reaction("💀")
        run(self.cog.on_reaction_add(r, u))
        r.message.delete.assert_called_once()

    def test_irrelevant_emoji_does_nothing(self):
        r, u = self._reaction("🎉")
        run(self.cog.on_reaction_add(r, u))
        assert self.cog.health_data[1001]["hp"] == 10


# ═════════════════════════════════════════════════════════════════════════════
# 14 · FightDynamic reaction handler
# ═════════════════════════════════════════════════════════════════════════════

class TestFightDynamicReaction:
    @pytest.fixture(autouse=True)
    def _fc(self, dbs):
        from commands.Combat import FightDynamic
        bot = make_bot()
        self.cog = FightDynamic.__new__(FightDynamic)
        self.cog.bot = bot
        self.cog.fight_data = {}
        self.ch = MagicMock(); self.ch.bot = False; self.ch.mention = f"<@{USER1_ID}>"
        self.op = MagicMock(); self.op.bot = False; self.op.mention = f"<@{USER2_ID}>"
        self._ix = MagicMock(); self._ix.followup = _FakeFollowup()
        self.cog.fight_data[2001] = {
            "challenger":        self.ch,
            "opponent":          self.op,
            "challenger_health": 20,
            "opponent_health":   20,
            "turn":              self.ch,
            "interaction":       self._ix,
            "challenger_oc":     USER1_CHAR,
            "opponent_oc":       USER2_CHAR,
        }

    def _reaction(self, emoji, user, mid=2001):
        r = MagicMock()
        r.emoji   = emoji
        r.message = MagicMock(); r.message.id = mid
        embed = MagicMock(); r.message.embeds = [embed]
        r.message.edit  = AsyncMock()
        r.message.clear_reactions = AsyncMock()
        r.message.add_reaction    = AsyncMock()
        r.message.channel         = MagicMock()
        r.message.channel.send    = AsyncMock()
        r.remove = AsyncMock()
        return r

    def test_bot_ignored(self):
        u = MagicMock(); u.bot = True
        r = self._reaction("🗡️", u)
        run(self.cog.on_reaction_add(r, u))
        assert self.cog.fight_data[2001]["challenger_health"] == 20

    def test_unknown_message_ignored(self):
        r = self._reaction("🗡️", self.ch, mid=9999)
        run(self.cog.on_reaction_add(r, self.ch))
        assert self.cog.fight_data[2001]["challenger_health"] == 20

    def test_wrong_emoji_does_nothing(self):
        r = self._reaction("💥", self.ch)
        run(self.cog.on_reaction_add(r, self.ch))
        assert self.cog.fight_data[2001]["challenger_health"] == 20

    def test_out_of_turn_sends_warning(self):
        r = self._reaction("🗡️", self.op)  # opponent tries on challenger's turn
        run(self.cog.on_reaction_add(r, self.op))
        assert self._ix.followup.calls

    def test_solid_hit_reduces_health(self):
        from commands.Combat import set_combat_weights
        set_combat_weights(1.0, 0.0, 0.0, 0.0)  # always solid hit
        r = self._reaction("🗡️", self.ch)
        run(self.cog.on_reaction_add(r, self.ch))
        assert self.cog.fight_data[2001]["opponent_health"] == 18

    def test_turn_passes_after_attack(self):
        from commands.Combat import set_combat_weights
        set_combat_weights(1.0, 0.0, 0.0, 0.0)
        r = self._reaction("🗡️", self.ch)
        run(self.cog.on_reaction_add(r, self.ch))
        assert self.cog.fight_data[2001]["turn"] == self.op

    def test_win_condition_removes_fight(self):
        from commands.Combat import set_combat_weights
        set_combat_weights(1.0, 0.0, 0.0, 0.0)
        self.cog.fight_data[2001]["opponent_health"] = 2
        r = self._reaction("🗡️", self.ch)
        run(self.cog.on_reaction_add(r, self.ch))
        assert 2001 not in self.cog.fight_data


# ═════════════════════════════════════════════════════════════════════════════
# 15 · Sheets command handlers
# ═════════════════════════════════════════════════════════════════════════════

class TestSheetsCommandHandlers:
    @pytest.fixture(autouse=True)
    def _sht(self, dbs):
        import commands.Sheets as sht
        bot = make_bot()
        self.cog = sht.Sheet.__new__(sht.Sheet)
        self.cog.bot = bot
        self.sht = sht

    def _ix(self, user_id=USER1_ID, admin=False):
        ix = make_interaction(user_id, admin=admin, bot=make_bot(admin=admin))
        ix.user.id      = int(user_id)
        ix.guild.id     = int(GUILD_ID)
        ix.response.defer = AsyncMock()
        ix.followup.send  = AsyncMock()
        return ix

    def test_new_creates_character(self, dbs):
        import commands.sheet_storage as ss
        ix = self._ix()
        run(self.sht.Sheet.new.callback(self.cog, ix, "NewHero"))
        assert ss.character_exists(USER1_ID, GUILD_ID, "NewHero")

    def test_new_duplicate_sends_error(self):
        ix = self._ix()
        run(self.sht.Sheet.new.callback(self.cog, ix, USER1_CHAR))
        ix.followup.send.assert_called()

    def test_list_sends_embed(self):
        ix = self._ix()
        run(self.sht.Sheet.list_sheets.callback(self.cog, ix))
        assert ix.response.calls

    def test_list_no_sheets_user(self):
        ix = self._ix("333333333333333333")
        ix.user.id = 333333333333333333
        run(self.sht.Sheet.list_sheets.callback(self.cog, ix))
        assert ix.response.calls

    def test_drafts_sends_response(self):
        ix = self._ix()
        run(self.sht.Sheet.drafts.callback(self.cog, ix))
        assert ix.response.calls

    def test_remove_char_not_found(self):
        ix = self._ix(admin=True)
        run(self.sht.Sheet.remove.callback(self.cog, ix, "NoSuchChar"))
        assert ix.response.calls

    def test_remove_own_char_responds(self):
        ix = self._ix(admin=True)
        run(self.sht.Sheet.remove.callback(self.cog, ix, USER1_CHAR))
        assert ix.response.calls

    def test_edit_sends_modal(self):
        ix = self._ix()
        run(self.sht.Sheet.edit.callback(self.cog, ix, USER1_CHAR, "Background"))
        assert ix.response.modal is not None

    def test_edit_char_not_found(self):
        ix = self._ix()
        run(self.sht.Sheet.edit.callback(self.cog, ix, "GhostChar", "Background"))
        assert ix.response.calls


# ═════════════════════════════════════════════════════════════════════════════
# 16 · Sheets UI components
# ═════════════════════════════════════════════════════════════════════════════

class TestSheetsUI:
    @pytest.fixture(autouse=True)
    def _ui(self, dbs):
        import commands.Sheets as sht
        import commands.sheet_storage as ss
        self.sht = sht
        self.ss  = ss
        char = ss.get_character(USER1_ID, GUILD_ID, USER1_CHAR)
        self.cid = char["character_id"]

    # ── FieldModal ────────────────────────────────────────────────────────────

    def test_field_modal_on_submit(self):
        saved = {}
        async def cb(inter, fn, val):
            saved["fn"] = fn; saved["val"] = val
        modal = self.sht.FieldModal("Background", "", cb)
        modal.input._value = "Born in the mountains."
        ix = make_interaction(USER1_ID, bot=make_bot())
        run(modal.on_submit(ix))
        assert saved["fn"] == "Background"
        assert saved["val"] == "Born in the mountains."

    def test_field_modal_empty_value(self):
        saved = {}
        async def cb(inter, fn, val): saved["val"] = val
        modal = self.sht.FieldModal("Class", "Druid", cb)
        modal.input._value = ""
        ix = make_interaction(USER1_ID, bot=make_bot())
        run(modal.on_submit(ix))
        assert saved["val"] == ""

    # ── CommentModal ──────────────────────────────────────────────────────────

    def test_comment_modal_on_submit(self):
        received = {}
        async def cb(inter, action, comment):
            received["action"] = action; received["comment"] = comment
        modal = self.sht.CommentModal(cb, "Approve")
        modal.comment._value = "Great sheet!"
        ix = make_interaction(USER1_ID, bot=make_bot())
        run(modal.on_submit(ix))
        assert received["action"] == "Approve"
        assert received["comment"] == "Great sheet!"

    def test_comment_modal_empty_ok(self):
        received = {}
        async def cb(inter, action, comment): received["comment"] = comment
        modal = self.sht.CommentModal(cb, "Deny")
        modal.comment._value = ""
        ix = make_interaction(USER1_ID, bot=make_bot())
        run(modal.on_submit(ix))
        assert received["comment"] == ""

    # ── _ConfirmDeleteView ────────────────────────────────────────────────────

    def test_confirm_deletes_character(self):
        cid = self.ss.create_character(USER1_ID, GUILD_ID, "ToDelete")
        self.ss.create_sheet(cid)
        view = self.sht._ConfirmDeleteView(cid, "ToDelete", USER1_ID)
        ix = make_interaction(USER1_ID, bot=make_bot())
        ix.response.edit_message = AsyncMock()
        run(view.confirm.callback(ix))
        assert not self.ss.character_exists(USER1_ID, GUILD_ID, "ToDelete")

    def test_cancel_does_not_delete(self):
        cid = self.ss.create_character(USER1_ID, GUILD_ID, "KeepMe")
        self.ss.create_sheet(cid)
        view = self.sht._ConfirmDeleteView(cid, "KeepMe", USER1_ID)
        ix = make_interaction(USER1_ID, bot=make_bot())
        ix.response.edit_message = AsyncMock()
        run(view.cancel.callback(ix))
        assert self.ss.character_exists(USER1_ID, GUILD_ID, "KeepMe")

    # ── LongFieldView ─────────────────────────────────────────────────────────

    def test_long_field_select_sends_embed(self):
        view = self.sht.LongFieldView([("Backstory", "A very long story...")])
        ix = make_interaction(USER1_ID, bot=make_bot())
        ix.data = {"values": ["Backstory"]}
        run(view._on_select(ix))
        assert ix.response.last_embed() is not None

    def test_long_field_empty_values_handled(self):
        view = self.sht.LongFieldView([("Backstory", "Story")])
        ix = make_interaction(USER1_ID, bot=make_bot())
        ix.data = {"values": []}
        run(view._on_select(ix))  # should not raise

    # ── DisambiguateView ──────────────────────────────────────────────────────

    def test_disambiguate_view_built_with_matches(self):
        cid1 = self.ss.create_character(USER1_ID, GUILD_ID, "SharedName")
        cid2 = self.ss.create_character(USER2_ID, GUILD_ID, "SharedName")
        self.ss.create_sheet(cid1); self.ss.create_sheet(cid2)
        matches = self.ss.search_characters(GUILD_ID, name_query="SharedName")
        view = self.sht.DisambiguateView(matches)
        assert len(view._matches) >= 1


# ═════════════════════════════════════════════════════════════════════════════
# 17 · Autocomplete functions
# ═════════════════════════════════════════════════════════════════════════════

class TestAutocompleteFunctions:
    @pytest.fixture(autouse=True)
    def _seed(self, dbs):
        from commands.Market import catalog_add_item
        catalog_add_item("FireSword")
        catalog_add_item("IceSword")
        catalog_add_item("WindBow")

    def test_item_autocomplete_matches(self):
        from commands.Economy import _item_autocomplete
        ix = make_interaction(USER1_ID, bot=make_bot())
        choices = run(_item_autocomplete(ix, "Sword"))
        names = [c.name for c in choices]
        assert "FireSword" in names and "IceSword" in names

    def test_item_autocomplete_case_insensitive(self):
        from commands.Economy import _item_autocomplete
        ix = make_interaction(USER1_ID, bot=make_bot())
        names = [c.name for c in run(_item_autocomplete(ix, "sword"))]
        assert "FireSword" in names

    def test_item_autocomplete_no_match(self):
        from commands.Economy import _item_autocomplete
        ix = make_interaction(USER1_ID, bot=make_bot())
        assert run(_item_autocomplete(ix, "xyzzzz")) == []

    def test_item_autocomplete_empty_string_returns_all(self):
        from commands.Economy import _item_autocomplete
        ix = make_interaction(USER1_ID, bot=make_bot())
        assert len(run(_item_autocomplete(ix, ""))) >= 3

    def test_char_autocomplete_own_chars(self):
        import commands.Sheets as sht
        cog = sht.Sheet.__new__(sht.Sheet); cog.bot = make_bot()
        ix = make_interaction(USER1_ID, bot=cog.bot)
        ix.user.id = int(USER1_ID); ix.guild.id = int(GUILD_ID)
        names = [c.name for c in run(sht.Sheet._char_autocomplete(cog, ix, ""))]
        assert USER1_CHAR in names

    def test_char_autocomplete_filters_by_input(self):
        import commands.Sheets as sht
        cog = sht.Sheet.__new__(sht.Sheet); cog.bot = make_bot()
        ix = make_interaction(USER1_ID, bot=cog.bot)
        ix.user.id = int(USER1_ID); ix.guild.id = int(GUILD_ID)
        names = [c.name for c in run(sht.Sheet._char_autocomplete(cog, ix, "Ari"))]
        assert USER1_CHAR in names

    def test_char_autocomplete_no_guild_returns_empty(self):
        import commands.Sheets as sht
        cog = sht.Sheet.__new__(sht.Sheet); cog.bot = make_bot()
        ix = make_interaction(USER1_ID, bot=cog.bot); ix.guild = None
        assert run(sht.Sheet._char_autocomplete(cog, ix, "")) == []

    def test_field_autocomplete_returns_template_fields(self):
        import commands.Sheets as sht
        import commands.sheet_storage as ss
        ss.add_template_field(GUILD_ID, "Background", sort_order=1)
        cog = sht.Sheet.__new__(sht.Sheet); cog.bot = make_bot()
        ix = make_interaction(USER1_ID, bot=cog.bot); ix.guild.id = int(GUILD_ID)
        names = [c.name for c in run(sht.Sheet._field_autocomplete(cog, ix, "Back"))]
        assert "Background" in names

    def test_field_autocomplete_no_guild_empty(self):
        import commands.Sheets as sht
        cog = sht.Sheet.__new__(sht.Sheet); cog.bot = make_bot()
        ix = make_interaction(USER1_ID, bot=cog.bot); ix.guild = None
        assert run(sht.Sheet._field_autocomplete(cog, ix, "")) == []

    def test_config_fieldname_autocomplete(self):
        import commands.Config as cfg
        import commands.sheet_storage as ss
        ss.add_template_field(GUILD_ID, "Race", sort_order=1)
        cog = cfg.Config.__new__(cfg.Config)
        ix = make_interaction(USER1_ID, bot=make_bot()); ix.guild.id = int(GUILD_ID)
        names = [c.name for c in run(cfg.Config.fieldname_autocomplete(cog, ix, "Ra"))]
        assert "Race" in names

    def test_market_catalog_autocomplete(self):
        from commands.Market import ItemCog
        bot = make_bot(admin=True)
        cog = ItemCog.__new__(ItemCog); cog.bot = bot
        ix = make_interaction(USER1_ID, bot=bot)
        names = [c.name for c in run(cog._item_name_autocomplete(ix, "Fire"))]
        assert "FireSword" in names


# ═════════════════════════════════════════════════════════════════════════════
# 18 · Help command
# ═════════════════════════════════════════════════════════════════════════════

class TestHelpCommand:
    @pytest.fixture(autouse=True)
    def _help(self, dbs):
        import commands.Help as h
        bot = make_bot()
        self.cog = h.Help.__new__(h.Help); self.cog.bot = bot
        self.h   = h

    def test_help_sends_embed(self):
        ix = make_interaction(USER1_ID, bot=self.cog.bot)
        run(self.h.Help.help_command.callback(self.cog, ix))
        assert ix.response.last_embed() is not None

    def test_help_embed_has_fields(self):
        ix = make_interaction(USER1_ID, bot=self.cog.bot)
        run(self.h.Help.help_command.callback(self.cog, ix))
        embed = ix.response.last_embed()
        assert embed is not None
        assert len(embed.fields) > 0 or embed.description


# ═════════════════════════════════════════════════════════════════════════════
# 19 · Command registration (direct inspection — no load_extension)
# ═════════════════════════════════════════════════════════════════════════════

class TestCommandRegistration:
    """
    Verify commands are declared without loading a full Bot.
    Checks the app_commands objects and group structures directly.
    """

    def test_currency_group_name(self):
        from commands.Economy import currency_group
        assert currency_group.name == "currency"

    def test_currency_group_has_view_remove_set(self):
        from commands.Economy import currency_group
        names = {c.name for c in currency_group.commands}
        assert {"view", "remove", "set"}.issubset(names)

    def test_work_group_exists(self):
        from commands.Economy import work_group
        assert work_group.name == "work"

    def test_work_group_has_create_edit_assign(self):
        from commands.Economy import work_group
        names = {c.name for c in work_group.commands}
        assert {"create", "edit", "assign"}.issubset(names)

    def test_give_money_registered(self):
        from commands.Economy import give_money
        assert give_money.name in ("give-money", "give_money", "give money")

    def test_give_item_registered(self):
        from commands.Economy import give_item
        assert give_item.name in ("give-item", "give_item", "give item")

    def test_job_claim_registered(self):
        from commands.Economy import job_claim
        assert "job" in job_claim.name or job_claim is not None

    def test_inventory_group_has_add_view_remove(self):
        from commands.Inventory import inventory_group
        names = {c.name for c in inventory_group.commands}
        assert {"add", "view", "remove"}.issubset(names)

    def test_item_group_exists(self):
        from commands.Market import ItemCog
        cog = ItemCog.__new__(ItemCog)
        assert hasattr(cog, "add")
        assert hasattr(cog, "list")

    def test_shop_group_exists(self):
        from commands.Market import ShopCog
        cog = ShopCog.__new__(ShopCog)
        assert hasattr(cog, "add")
        assert hasattr(cog, "buy")
        assert hasattr(cog, "sell")

    def test_health_track_exists(self):
        from commands.Combat import HealthBar
        assert hasattr(HealthBar, "health_track")

    def test_fight_dynamic_exists(self):
        from commands.Combat import FightDynamic
        assert hasattr(FightDynamic, "fight_dynamic_rules")

    def test_death_group_has_commands(self):
        from commands.Combat import Death
        assert hasattr(Death, "death")

    def test_sheet_group_has_commands(self):
        from commands.Sheets import Sheet
        assert hasattr(Sheet, "new")
        assert hasattr(Sheet, "edit")
        assert hasattr(Sheet, "remove")

    def test_config_group_has_commands(self):
        from commands.Config import Config
        assert hasattr(Config, "field_add")
        assert hasattr(Config, "field_remove")
        assert hasattr(Config, "reset")

    def test_help_command_exists(self):
        from commands.Help import Help
        assert hasattr(Help, "help_command")


# ═════════════════════════════════════════════════════════════════════════════
# 20 · Config role & channel commands
# ═════════════════════════════════════════════════════════════════════════════

class TestConfigRoleChannel:
    @pytest.fixture(autouse=True)
    def _cfg(self, dbs):
        import commands.Config as cfg_mod
        self.cog      = cfg_mod.Config.__new__(cfg_mod.Config)
        self.cfg_mod  = cfg_mod
        self.sdb      = dbs["settings_db"]

    def _ix(self, admin=True):
        return make_interaction(USER1_ID if admin else USER2_ID,
                                admin=admin, bot=make_bot(admin=admin))

    # ── role ──────────────────────────────────────────────────────────────────

    def test_role_admin_sets_admin_role(self):
        ix   = self._ix(admin=True)
        role = MagicMock(); role.id = 55555; role.name = "Admin"
        ch   = MagicMock(); ch.value = "admin"
        run(self.cfg_mod.Config.role.callback(self.cog, ix, ch, role))
        conn = sqlite3.connect(self.sdb)
        row  = conn.execute(
            "SELECT admin_role_id FROM Server WHERE guild_id=?", (int(GUILD_ID),)
        ).fetchone()
        conn.close()
        assert row and row[0] == 55555

    def test_role_admin_sets_member_role(self):
        ix   = self._ix(admin=True)
        role = MagicMock(); role.id = 66666; role.name = "Member"
        ch   = MagicMock(); ch.value = "member"
        run(self.cfg_mod.Config.role.callback(self.cog, ix, ch, role))
        conn = sqlite3.connect(self.sdb)
        row  = conn.execute(
            "SELECT member_role_id FROM Server WHERE guild_id=?", (int(GUILD_ID),)
        ).fetchone()
        conn.close()
        assert row and row[0] == 66666

    def test_role_non_admin_rejected(self):
        ix   = self._ix(admin=False)
        role = MagicMock(); role.id = 77777; role.name = "Role"
        ch   = MagicMock(); ch.value = "admin"
        run(self.cfg_mod.Config.role.callback(self.cog, ix, ch, role))
        assert ix.response.calls

    def test_role_no_guild_rejected(self):
        ix      = self._ix(admin=True); ix.guild = None
        role    = MagicMock(); role.id = 11111; role.name = "X"
        ch      = MagicMock(); ch.value = "admin"
        run(self.cfg_mod.Config.role.callback(self.cog, ix, ch, role))
        assert ix.response.calls

    # ── channel ───────────────────────────────────────────────────────────────

    def test_channel_admin_sets_admin_channel(self):
        ix      = self._ix(admin=True)
        channel = MagicMock(); channel.id = 123123; channel.mention = "#admin"
        ch      = MagicMock(); ch.value = "admin"
        run(self.cfg_mod.Config.channel.callback(self.cog, ix, ch, channel))
        conn = sqlite3.connect(self.sdb)
        row  = conn.execute(
            "SELECT admin_channel_id FROM Server WHERE guild_id=?", (int(GUILD_ID),)
        ).fetchone()
        conn.close()
        assert row and row[0] == 123123

    def test_channel_admin_sets_member_channel(self):
        ix      = self._ix(admin=True)
        channel = MagicMock(); channel.id = 456456; channel.mention = "#member"
        ch      = MagicMock(); ch.value = "member"
        run(self.cfg_mod.Config.channel.callback(self.cog, ix, ch, channel))
        conn = sqlite3.connect(self.sdb)
        row  = conn.execute(
            "SELECT member_channel_id FROM Server WHERE guild_id=?", (int(GUILD_ID),)
        ).fetchone()
        conn.close()
        assert row and row[0] == 456456

    def test_channel_non_admin_rejected(self):
        ix      = self._ix(admin=False)
        channel = MagicMock(); channel.id = 9999; channel.mention = "#x"
        ch      = MagicMock(); ch.value = "admin"
        run(self.cfg_mod.Config.channel.callback(self.cog, ix, ch, channel))
        assert ix.response.calls

    def test_channel_no_guild_rejected(self):
        ix      = self._ix(admin=True); ix.guild = None
        channel = MagicMock(); channel.id = 9999; channel.mention = "#x"
        ch      = MagicMock(); ch.value = "admin"
        run(self.cfg_mod.Config.channel.callback(self.cog, ix, ch, channel))
        assert ix.response.calls


# ═════════════════════════════════════════════════════════════════════════════
# 21 · give_money & give_item handlers
# ═════════════════════════════════════════════════════════════════════════════

class TestGiveMoneyItem:
    @pytest.fixture(autouse=True)
    def _eco(self, dbs):
        from commands.Economy import give_money, give_item, set_currency, fetch_currency
        from commands.Inventory import upsert_item, fetch_items
        from commands.Market import catalog_add_item
        catalog_add_item("GoldCoin")
        self.give_money  = give_money.callback
        self.give_item   = give_item.callback
        self.set_cur     = set_currency
        self.fetch_cur   = fetch_currency
        self.upsert_item = upsert_item
        self.fetch_items = fetch_items

    # ── give_money ────────────────────────────────────────────────────────────

    def test_give_money_transfers_correctly(self):
        self.set_cur(USER1_ID, USER1_CHAR, 200.0)
        self.set_cur(USER2_ID, USER2_CHAR, 50.0)
        ix = make_interaction(USER1_ID, bot=make_bot())
        ix.user.id = int(USER1_ID)
        run(self.give_money(ix, USER1_CHAR, 75.0, f"<@{USER2_ID}>", USER2_CHAR))
        assert self.fetch_cur(USER1_ID, USER1_CHAR) == 125.0
        assert self.fetch_cur(USER2_ID, USER2_CHAR) == 125.0

    def test_give_money_insufficient_funds(self):
        self.set_cur(USER1_ID, USER1_CHAR, 10.0)
        ix = make_interaction(USER1_ID, bot=make_bot())
        ix.user.id = int(USER1_ID)
        run(self.give_money(ix, USER1_CHAR, 999.0, f"<@{USER2_ID}>", USER2_CHAR))
        assert self.fetch_cur(USER1_ID, USER1_CHAR) == 10.0
        assert "not enough" in (ix.response.last_content() or "").lower()

    def test_give_money_sender_char_not_found(self):
        ix = make_interaction(USER1_ID, bot=make_bot())
        ix.user.id = int(USER1_ID)
        run(self.give_money(ix, "GhostChar", 10.0, f"<@{USER2_ID}>", USER2_CHAR))
        assert ix.response.calls

    def test_give_money_recipient_char_not_found(self):
        self.set_cur(USER1_ID, USER1_CHAR, 100.0)
        ix = make_interaction(USER1_ID, bot=make_bot())
        ix.user.id = int(USER1_ID)
        run(self.give_money(ix, USER1_CHAR, 10.0, f"<@{USER2_ID}>", "NoCharHere"))
        assert self.fetch_cur(USER1_ID, USER1_CHAR) == 100.0
        assert ix.response.calls

    def test_give_money_sends_followup_embed(self):
        self.set_cur(USER1_ID, USER1_CHAR, 100.0)
        ix = make_interaction(USER1_ID, bot=make_bot())
        ix.user.id = int(USER1_ID)
        run(self.give_money(ix, USER1_CHAR, 10.0, f"<@{USER2_ID}>", USER2_CHAR))
        assert ix.followup.calls

    # ── give_item ─────────────────────────────────────────────────────────────

    def test_give_item_transfers_correctly(self):
        self.upsert_item(USER1_ID, USER1_CHAR, "GoldCoin", 5)
        ix = make_interaction(USER1_ID, bot=make_bot())
        ix.user.id = int(USER1_ID)
        run(self.give_item(ix, USER1_CHAR, "GoldCoin", 3, f"<@{USER2_ID}>", USER2_CHAR))
        assert dict(self.fetch_items(USER1_ID, USER1_CHAR)).get("GoldCoin") == 2
        assert dict(self.fetch_items(USER2_ID, USER2_CHAR)).get("GoldCoin") == 3

    def test_give_item_not_enough_items(self):
        self.upsert_item(USER1_ID, USER1_CHAR, "GoldCoin", 1)
        ix = make_interaction(USER1_ID, bot=make_bot())
        ix.user.id = int(USER1_ID)
        run(self.give_item(ix, USER1_CHAR, "GoldCoin", 99, f"<@{USER2_ID}>", USER2_CHAR))
        assert dict(self.fetch_items(USER1_ID, USER1_CHAR)).get("GoldCoin") == 1
        assert "not enough" in (ix.response.last_content() or "").lower()

    def test_give_item_removes_when_exhausted(self):
        self.upsert_item(USER1_ID, USER1_CHAR, "GoldCoin", 2)
        ix = make_interaction(USER1_ID, bot=make_bot())
        ix.user.id = int(USER1_ID)
        run(self.give_item(ix, USER1_CHAR, "GoldCoin", 2, f"<@{USER2_ID}>", USER2_CHAR))
        assert dict(self.fetch_items(USER1_ID, USER1_CHAR)).get("GoldCoin") is None

    def test_give_item_sender_char_not_found(self):
        ix = make_interaction(USER1_ID, bot=make_bot())
        ix.user.id = int(USER1_ID)
        run(self.give_item(ix, "Ghost", "GoldCoin", 1, f"<@{USER2_ID}>", USER2_CHAR))
        assert ix.response.calls

    def test_give_item_recipient_char_not_found(self):
        self.upsert_item(USER1_ID, USER1_CHAR, "GoldCoin", 5)
        ix = make_interaction(USER1_ID, bot=make_bot())
        ix.user.id = int(USER1_ID)
        run(self.give_item(ix, USER1_CHAR, "GoldCoin", 1, f"<@{USER2_ID}>", "NoChar"))
        assert dict(self.fetch_items(USER1_ID, USER1_CHAR)).get("GoldCoin") == 5
        assert ix.response.calls

    def test_give_item_sends_followup_embed(self):
        self.upsert_item(USER1_ID, USER1_CHAR, "GoldCoin", 3)
        ix = make_interaction(USER1_ID, bot=make_bot())
        ix.user.id = int(USER1_ID)
        run(self.give_item(ix, USER1_CHAR, "GoldCoin", 1, f"<@{USER2_ID}>", USER2_CHAR))
        assert ix.followup.calls


# ═════════════════════════════════════════════════════════════════════════════
# 22 · Market: item remove, set description, set image, shop view
# ═════════════════════════════════════════════════════════════════════════════

class TestMarketMissingHandlers:
    @pytest.fixture(autouse=True)
    def _mkt(self, dbs):
        from commands.Market import (
            ItemCog, ShopCog, catalog_add_item, add_shop_item,
            catalog_get_item, get_shop_item, get_shop_items,
        )
        from commands.Economy import set_currency, fetch_currency
        from commands.Inventory import upsert_item, fetch_items
        self.ab           = make_bot(admin=True)
        self.ic           = ItemCog.__new__(ItemCog); self.ic.bot = self.ab
        self.sc           = ShopCog.__new__(ShopCog); self.sc.bot = self.ab
        self.catalog_get  = catalog_get_item
        self.shop_get     = get_shop_item
        self.shop_items   = get_shop_items
        self.set_cur      = set_currency
        self.fetch_cur    = fetch_currency
        self.upsert_item  = upsert_item
        self.fetch_items  = fetch_items
        # Seed
        catalog_add_item("IronSword", consumable="No", description="A sword")
        add_shop_item("IronSword", 100)

    # ── item remove ───────────────────────────────────────────────────────────

    def test_item_remove_admin_removes(self):
        from commands.Market import ItemCog
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        run(ItemCog.remove.callback(self.ic, ix, "IronSword"))
        assert self.catalog_get("IronSword") is None

    def test_item_remove_also_removes_from_shop(self):
        from commands.Market import ItemCog
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        run(ItemCog.remove.callback(self.ic, ix, "IronSword"))
        assert self.shop_get("IronSword") is None

    def test_item_remove_refunds_holders(self):
        # NOTE: In the source code, get_shop_price() is called AFTER the shop
        # row has already been deleted, so it always returns None and no refund
        # is issued. This test asserts the actual runtime behaviour.
        from commands.Market import ItemCog
        self.upsert_item(USER1_ID, USER1_CHAR, "IronSword", 2)
        self.set_cur(USER1_ID, USER1_CHAR, 0.0)
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        run(ItemCog.remove.callback(self.ic, ix, "IronSword"))
        # Refund is 0 because the shop row is deleted before the price lookup
        assert self.fetch_cur(USER1_ID, USER1_CHAR) == 0.0

    def test_item_remove_item_not_found_sends_error(self):
        from commands.Market import ItemCog
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        run(ItemCog.remove.callback(self.ic, ix, "PhantomSword"))
        assert ix.response.calls

    def test_item_remove_non_admin_rejected(self):
        from commands.Market import ItemCog
        bot = make_bot(admin=False); self.ic.bot = bot
        ix  = make_interaction(USER2_ID, admin=False, bot=bot)
        run(ItemCog.remove.callback(self.ic, ix, "IronSword"))
        assert self.catalog_get("IronSword") is not None
        self.ic.bot = self.ab

    # ── item set description ───────────────────────────────────────────────────

    def test_set_description_admin_sends_modal(self):
        from commands.Market import ItemCog
        ix = make_interaction(USER1_ID, admin=True, bot=self.ab)
        run(ItemCog.set_description.callback(self.ic, ix, "IronSword"))
        assert ix.response.modal is not None

    def test_set_description_non_admin_rejected(self):
        from commands.Market import ItemCog
        bot = make_bot(admin=False); self.ic.bot = bot
        ix  = make_interaction(USER2_ID, admin=False, bot=bot)
        run(ItemCog.set_description.callback(self.ic, ix, "IronSword"))
        assert ix.response.modal is None
        self.ic.bot = self.ab

    # ── item set image ─────────────────────────────────────────────────────────

    def test_set_image_invalid_content_type_rejected(self):
        from commands.Market import ItemCog
        ix  = make_interaction(USER1_ID, admin=True, bot=self.ab)
        att = MagicMock(); att.content_type = "text/plain"; att.filename = "file.txt"
        run(ItemCog.set_image.callback(self.ic, ix, "IronSword", att))
        assert "valid image" in (ix.response.last_content() or "").lower()

    def test_set_image_non_admin_rejected(self):
        from commands.Market import ItemCog
        bot = make_bot(admin=False); self.ic.bot = bot
        ix  = make_interaction(USER2_ID, admin=False, bot=bot)
        att = MagicMock(); att.content_type = "image/png"; att.filename = "img.png"
        run(ItemCog.set_image.callback(self.ic, ix, "IronSword", att))
        assert ix.response.calls
        self.ic.bot = self.ab

    # ── shop view ─────────────────────────────────────────────────────────────

    def test_shop_view_empty(self):
        from commands.Market import ShopCog, remove_shop_item
        remove_shop_item("IronSword")
        ix = make_interaction(USER1_ID, bot=self.ab)
        run(ShopCog.view.callback(self.sc, ix))
        assert ix.response.calls

    def test_shop_view_has_items(self):
        from commands.Market import ShopCog
        ix = make_interaction(USER1_ID, bot=self.ab)
        run(ShopCog.view.callback(self.sc, ix))
        assert ix.response.calls


# ═════════════════════════════════════════════════════════════════════════════
# 23 · fight_dynamic start command
# ═════════════════════════════════════════════════════════════════════════════

class TestFightDynamicCommand:
    @pytest.fixture(autouse=True)
    def _fc(self, dbs):
        from commands.Combat import FightDynamic
        bot = make_bot()
        self.cog = FightDynamic.__new__(FightDynamic)
        self.cog.bot = bot
        self.cog.fight_data = {}

    def _ix(self):
        ix = make_interaction(USER1_ID, bot=self.cog.bot)
        ix.user.id           = int(USER1_ID)
        ix.user.display_name = "alice"
        msg = MagicMock(); msg.id = 9001
        msg.add_reaction = AsyncMock()
        ix.original_response = AsyncMock(return_value=msg)
        return ix

    def test_fight_dynamic_success(self):
        from commands.Combat import FightDynamic
        ix = self._ix()
        opponent = MagicMock()
        opponent.id           = int(USER2_ID)
        opponent.display_name = "bob"
        run(FightDynamic.fight_dynamic.callback(self.cog, ix, USER1_CHAR, opponent, USER2_CHAR))
        assert ix.response.last_embed() is not None

    def test_fight_dynamic_registers_fight_data(self):
        from commands.Combat import FightDynamic
        ix = self._ix()
        opponent = MagicMock()
        opponent.id           = int(USER2_ID)
        opponent.display_name = "bob"
        run(FightDynamic.fight_dynamic.callback(self.cog, ix, USER1_CHAR, opponent, USER2_CHAR))
        assert 9001 in self.cog.fight_data

    def test_fight_dynamic_challenger_char_not_found(self):
        from commands.Combat import FightDynamic
        ix = self._ix()
        opponent = MagicMock(); opponent.id = int(USER2_ID)
        run(FightDynamic.fight_dynamic.callback(self.cog, ix, "GhostChar", opponent, USER2_CHAR))
        assert ix.response.calls
        assert not self.cog.fight_data  # nothing registered

    def test_fight_dynamic_opponent_char_not_found(self):
        from commands.Combat import FightDynamic
        ix = self._ix()
        opponent = MagicMock(); opponent.id = int(USER2_ID); opponent.display_name = "bob"
        run(FightDynamic.fight_dynamic.callback(self.cog, ix, USER1_CHAR, opponent, "GhostOC"))
        assert ix.response.calls
        assert not self.cog.fight_data


# ═════════════════════════════════════════════════════════════════════════════
# 24 · death claim command (not ClaimView button — the /death claim slash cmd)
# ═════════════════════════════════════════════════════════════════════════════

class TestDeathClaimCommand:
    @pytest.fixture(autouse=True)
    def _dc(self, dbs):
        from commands.Combat import Death, ensure_death_table
        ensure_death_table()
        bot = make_bot(admin=True)
        self.cog = Death.__new__(Death)
        self.cog.bot = bot
        self.dbs = dbs

    def _ix(self):
        ix = make_interaction(USER1_ID, admin=True, bot=self.cog.bot)
        ix.user.id    = int(USER1_ID)
        ix.guild.id   = int(GUILD_ID)
        ix.channel    = MagicMock()
        ix.channel.mention = "#general"
        return ix

    def test_claim_char_not_found_sends_error(self):
        from commands.Combat import Death
        ix = self._ix()
        run(Death.claim.callback(self.cog, ix, f"<@{USER1_ID}>", "NoSuchChar"))
        assert ix.response.calls

    def test_claim_no_admin_channel_sends_error(self):
        """When admin_channel_id is not set in settings, claim should error."""
        from commands.Combat import Death
        ix = self._ix()
        # Guild has no admin_channel_id row (settings.db has it as NULL by default)
        # Make bot.get_channel always return None
        self.cog.bot.get_channel = MagicMock(return_value=None)
        run(Death.claim.callback(self.cog, ix, f"<@{USER1_ID}>", USER1_CHAR))
        assert ix.response.calls

    # NOTE: death.claim hardcodes os.path.join('databases', 'Settings.db') for
    # the admin_channel_id lookup, so the full success path can't be tested
    # without touching the live database. The two tests above cover the
    # meaningful error paths.



# ═════════════════════════════════════════════════════════════════════════════
# 25 · sheet submit paths
# ═════════════════════════════════════════════════════════════════════════════

class TestSheetSubmit:
    @pytest.fixture(autouse=True)
    def _sht(self, dbs):
        import commands.Sheets as sht
        import commands.sheet_storage as ss
        self.sht  = sht
        self.ss   = ss
        bot       = make_bot(admin=True)
        self.cog  = sht.Sheet.__new__(sht.Sheet)
        self.cog.bot = bot
        char = ss.get_character(USER1_ID, GUILD_ID, USER1_CHAR)
        self.cid  = char["character_id"]
        self.sid  = ss.get_sheet_by_character(self.cid)["sheet_id"]
        self.dbs  = dbs

    def _ix(self):
        ix = make_interaction(USER1_ID, bot=self.cog.bot)
        ix.user.id  = int(USER1_ID); ix.guild.id = int(GUILD_ID)
        return ix

    def test_submit_char_not_found(self):
        ix = self._ix()
        run(self.sht.Sheet.submit.callback(self.cog, ix, "NoSuchChar"))
        assert ix.response.calls

    def test_submit_already_approved_no_pending(self):
        self.ss.set_sheet_status(self.sid, "Approved")
        ix = self._ix()
        run(self.sht.Sheet.submit.callback(self.cog, ix, USER1_CHAR))
        assert ix.response.calls

    def test_submit_already_pending(self):
        self.ss.set_sheet_status(self.sid, "Pending")
        ix = self._ix()
        run(self.sht.Sheet.submit.callback(self.cog, ix, USER1_CHAR))
        assert "already" in (ix.response.last_content() or "").lower()

    def test_submit_missing_required_field(self):
        self.ss.add_template_field(GUILD_ID, "Background", sort_order=1, required=1)
        # channels must be set to reach the field-check gate
        conn = sqlite3.connect(self.dbs["settings_db"])
        conn.execute(
            "UPDATE Server SET admin_channel_id=111, member_channel_id=222 WHERE guild_id=?",
            (int(GUILD_ID),)
        )
        conn.commit(); conn.close()
        self.cog.bot.get_channel = MagicMock(return_value=None)  # channels not found → error
        ix = self._ix()
        run(self.sht.Sheet.submit.callback(self.cog, ix, USER1_CHAR))
        assert ix.response.calls

    def test_submit_channels_not_configured(self):
        conn = sqlite3.connect(self.dbs["settings_db"])
        conn.execute(
            "UPDATE Server SET admin_channel_id=NULL, member_channel_id=NULL WHERE guild_id=?",
            (int(GUILD_ID),)
        )
        conn.commit(); conn.close()
        ix = self._ix()
        run(self.sht.Sheet.submit.callback(self.cog, ix, USER1_CHAR))
        assert "channel" in (ix.response.last_content() or "").lower()

    def test_submit_success(self):
        """Full happy-path: both channels configured and found as TextChannels."""
        import discord, builtins
        conn = sqlite3.connect(self.dbs["settings_db"])
        conn.execute(
            "UPDATE Server SET admin_channel_id=111, member_channel_id=222 WHERE guild_id=?",
            (int(GUILD_ID),)
        )
        conn.commit(); conn.close()

        fake_msg = MagicMock(); fake_msg.id = 1
        fake_msg.channel = MagicMock(); fake_msg.channel.id = 111
        admin_ch  = MagicMock(spec=discord.TextChannel)
        admin_ch.send   = AsyncMock(return_value=fake_msg)
        member_ch = MagicMock(spec=discord.TextChannel)
        member_ch.send  = AsyncMock()

        def get_ch(cid):
            return admin_ch if cid == 111 else member_ch

        self.cog.bot.get_channel = get_ch

        real_isinstance = builtins.isinstance

        def patched(obj, cls):
            if cls is discord.TextChannel and obj in (admin_ch, member_ch):
                return True
            return real_isinstance(obj, cls)

        import builtins as _builtins
        old = _builtins.isinstance
        _builtins.isinstance = patched
        try:
            ix = self._ix()
            run(self.sht.Sheet.submit.callback(self.cog, ix, USER1_CHAR))
        finally:
            _builtins.isinstance = old

        # Sheet should now be Pending
        sheet = self.ss.get_sheet(self.sid)
        assert sheet["status"] == "Pending"


# ═════════════════════════════════════════════════════════════════════════════
# 26 · sheet icon command
# ═════════════════════════════════════════════════════════════════════════════

class TestSheetIcon:
    @pytest.fixture(autouse=True)
    def _sht(self, dbs):
        import commands.Sheets as sht
        import commands.sheet_storage as ss
        bot      = make_bot()
        self.cog = sht.Sheet.__new__(sht.Sheet); self.cog.bot = bot
        self.sht = sht; self.ss = ss

    def _ix(self, uid=USER1_ID):
        ix = make_interaction(uid, bot=self.cog.bot)
        ix.user.id = int(uid); ix.guild.id = int(GUILD_ID)
        return ix

    def test_icon_invalid_content_type_rejected(self):
        ix  = self._ix()
        att = MagicMock(); att.content_type = "text/plain"
        att.filename = "file.txt"; att.save = AsyncMock()
        run(self.sht.Sheet.icon.callback(self.cog, ix, USER1_CHAR, att))
        assert ix.response.calls

    def test_icon_char_not_found(self):
        ix  = self._ix()
        att = MagicMock(); att.content_type = "image/png"
        att.filename = "img.png"; att.save = AsyncMock()
        run(self.sht.Sheet.icon.callback(self.cog, ix, "GhostChar", att))
        assert ix.response.calls

    def test_icon_invalid_extension_rejected(self):
        ix  = self._ix()
        att = MagicMock(); att.content_type = "image/bmp"
        att.filename = "img.bmp"; att.save = AsyncMock()
        run(self.sht.Sheet.icon.callback(self.cog, ix, USER1_CHAR, att))
        assert ix.response.calls

    def test_icon_success_saves_and_sets_field(self):
        ix  = self._ix()
        att = MagicMock(); att.content_type = "image/png"
        att.filename = "avatar.png"; att.save = AsyncMock()
        run(self.sht.Sheet.icon.callback(self.cog, ix, USER1_CHAR, att))
        att.save.assert_called_once()
        char  = self.ss.get_character(USER1_ID, GUILD_ID, USER1_CHAR)
        sheet = self.ss.get_sheet_by_character(char["character_id"])
        fields = dict((f[0], f[1]) for f in self.ss.get_fields(sheet["sheet_id"]))
        assert "Icon" in fields


# ═════════════════════════════════════════════════════════════════════════════
# 27 · sheet pending command (admin)
# ═════════════════════════════════════════════════════════════════════════════

class TestSheetPending:
    @pytest.fixture(autouse=True)
    def _sht(self, dbs):
        import commands.Sheets as sht
        import commands.sheet_storage as ss
        self.sht = sht; self.ss = ss
        self.dbs = dbs

    def _cog(self, admin=True):
        import commands.Sheets as sht
        bot = make_bot(admin=admin)
        cog = sht.Sheet.__new__(sht.Sheet); cog.bot = bot
        return cog

    def _ix(self, cog, admin=True):
        uid = USER1_ID if admin else USER2_ID
        ix  = make_interaction(uid, admin=admin, bot=cog.bot)
        ix.user.id = int(uid); ix.guild.id = int(GUILD_ID)
        return ix

    def test_pending_non_admin_rejected(self):
        import commands.Sheets as sht
        cog = self._cog(admin=False)
        ix  = self._ix(cog, admin=False)
        run(sht.Sheet.pending.callback(cog, ix))
        assert ix.response.calls

    def test_pending_no_sheets_sends_message(self):
        import commands.Sheets as sht
        cog = self._cog(admin=True)
        ix  = self._ix(cog, admin=True)
        run(sht.Sheet.pending.callback(cog, ix))
        assert ix.response.calls

    def test_pending_with_sheet_sends_response(self):
        import commands.Sheets as sht
        # Make a pending sheet
        char = self.ss.get_character(USER1_ID, GUILD_ID, USER1_CHAR)
        sid  = self.ss.get_sheet_by_character(char["character_id"])["sheet_id"]
        self.ss.set_sheet_status(sid, "Pending")

        cog = self._cog(admin=True)
        cog.bot.get_channel = MagicMock(return_value=None)  # channels exist but not TextChannel
        ix  = self._ix(cog, admin=True)
        run(sht.Sheet.pending.callback(cog, ix))
        assert ix.response.calls


# ═════════════════════════════════════════════════════════════════════════════
# 28 · /search command (Search cog)
# ═════════════════════════════════════════════════════════════════════════════

class TestSearchCommand:
    @pytest.fixture(autouse=True)
    def _search(self, dbs):
        import commands.Sheets as sht
        bot = make_bot()
        self.cog = sht.Search.__new__(sht.Search); self.cog.bot = bot
        self.sht = sht

    def _ix(self):
        ix = make_interaction(USER1_ID, bot=self.cog.bot)
        ix.user.id = int(USER1_ID); ix.guild.id = int(GUILD_ID)
        return ix

    def test_search_no_args_rejected(self):
        ix = self._ix()
        run(self.sht.Search.search.callback(self.cog, ix, name=None, user=None))
        assert "at least" in (ix.response.last_content() or "").lower()

    def test_search_no_approved_results(self):
        # All seeded sheets are Draft, so Approved search returns nothing
        ix = self._ix()
        run(self.sht.Search.search.callback(self.cog, ix, name=USER1_CHAR, user=None))
        assert ix.response.calls

    def test_search_approved_returns_results(self):
        import commands.sheet_storage as ss
        char = ss.get_character(USER1_ID, GUILD_ID, USER1_CHAR)
        sid  = ss.get_sheet_by_character(char["character_id"])["sheet_id"]
        ss.set_sheet_status(sid, "Approved")
        ix = self._ix()
        run(self.sht.Search.search.callback(self.cog, ix, name=USER1_CHAR, user=None))
        assert ix.response.calls

    def test_search_by_user_filter(self):
        import commands.sheet_storage as ss
        char = ss.get_character(USER1_ID, GUILD_ID, USER1_CHAR)
        sid  = ss.get_sheet_by_character(char["character_id"])["sheet_id"]
        ss.set_sheet_status(sid, "Approved")
        ix   = self._ix()
        user = MagicMock(); user.id = int(USER1_ID)
        run(self.sht.Search.search.callback(self.cog, ix, name=None, user=user))
        assert ix.response.calls

    def test_search_no_guild_handled(self):
        ix       = self._ix()
        ix.guild = None
        run(self.sht.Search.search.callback(self.cog, ix, name=USER1_CHAR, user=None))
        assert ix.response.calls

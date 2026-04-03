###################################################################
# sheet_storage.py — Data-access layer for Sheets.db            #
###################################################################
#
# Schema (databases/Sheets.db)
# ─────────────────────────────
#   characters      — authoritative identity: (user_id, guild_id, name)
#   sheets          — one sheet per character, holds status + timestamps
#   sheet_fields    — unlimited key/value pairs; value is full TEXT (no cap)
#   guild_templates — ordered default fields per Discord server
#   pending_reviews — active admin-review message reference (one per sheet)
#   sheet_reviews   — full audit trail of every admin action
#
# Other DBs touched from here
# ────────────────────────────
#   databases/Settings.db — Server table, for channel ID lookups (read-only)
#
###################################################################

import os
import sqlite3
import time
from typing import Optional

_BASE       = os.path.dirname(os.path.dirname(__file__))
SHEETS_DB   = os.path.join(_BASE, 'databases', 'Sheets.db')
SETTINGS_DB = os.path.join(_BASE, 'databases', 'Settings.db')


# ─── Connection ───────────────────────────────────────────────────────────────

def connect_db() -> sqlite3.Connection:
    """Open a hardened connection to Sheets.db (WAL, full sync, foreign keys)."""
    os.makedirs(os.path.dirname(SHEETS_DB), exist_ok=True)
    conn = sqlite3.connect(SHEETS_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# ─── Schema ───────────────────────────────────────────────────────────────────

def ensure_schema() -> None:
    """Create all tables and indices. Safe to call on every bot startup."""
    conn = connect_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS characters (
                character_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT    NOT NULL,
                guild_id     TEXT    NOT NULL,
                name         TEXT    NOT NULL,
                created_at   INTEGER NOT NULL,
                UNIQUE (user_id, guild_id, name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sheets (
                sheet_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL
                    REFERENCES characters(character_id) ON DELETE CASCADE,
                status       TEXT    NOT NULL DEFAULT 'Draft',
                created_at   INTEGER NOT NULL,
                updated_at   INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sheet_fields (
                field_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                sheet_id   INTEGER NOT NULL
                    REFERENCES sheets(sheet_id) ON DELETE CASCADE,
                field_name TEXT    NOT NULL,
                value      TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL,
                UNIQUE (sheet_id, field_name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS guild_templates (
                template_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT    NOT NULL,
                field_name  TEXT    NOT NULL,
                sort_order  INTEGER NOT NULL DEFAULT 0,
                required    INTEGER NOT NULL DEFAULT 0,
                UNIQUE (guild_id, field_name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_reviews (
                sheet_id           INTEGER PRIMARY KEY
                    REFERENCES sheets(sheet_id) ON DELETE CASCADE,
                discord_channel_id TEXT,
                discord_message_id TEXT,
                submitted_at       INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sheet_reviews (
                review_id          INTEGER PRIMARY KEY AUTOINCREMENT,
                sheet_id           INTEGER NOT NULL
                    REFERENCES sheets(sheet_id) ON DELETE CASCADE,
                reviewer_id        TEXT    NOT NULL,
                action             TEXT    NOT NULL,
                comment            TEXT,
                discord_message_id TEXT,
                timestamp          INTEGER NOT NULL
            )
        """)
        # Indices
        conn.execute("CREATE INDEX IF NOT EXISTS idx_char_user_guild ON characters (user_id, guild_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sheets_char     ON sheets (character_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fields_sheet    ON sheet_fields (sheet_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_template_guild  ON guild_templates (guild_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_sheet   ON sheet_reviews (sheet_id)")
        conn.commit()
    finally:
        conn.close()


# ─── Characters ───────────────────────────────────────────────────────────────

def character_exists(user_id: str, guild_id: str, name: str) -> bool:
    """Return True if this character name exists for the user in the guild."""
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM characters WHERE user_id=? AND guild_id=? AND name=? COLLATE NOCASE",
            (user_id, guild_id, name),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def create_character(user_id: str, guild_id: str, name: str) -> int:
    """
    Insert a new character and return its character_id.
    Raises ValueError if the name already exists for this user+guild.
    """
    now = int(time.time())
    conn = connect_db()
    try:
        try:
            cur = conn.execute(
                "INSERT INTO characters (user_id, guild_id, name, created_at) VALUES (?, ?, ?, ?)",
                (user_id, guild_id, name, now),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"A character named '{name}' already exists.")
        character_id = cur.lastrowid
        conn.commit()
        return character_id
    finally:
        conn.close()


def get_character(user_id: str, guild_id: str, name: str) -> Optional[dict]:
    """Return the character row as a dict, or None (case-insensitive name match)."""
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT * FROM characters WHERE user_id=? AND guild_id=? AND name=? COLLATE NOCASE",
            (user_id, guild_id, name),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_characters(user_id: str, guild_id: str) -> list:
    """Return all characters for a user in a guild ordered by creation time."""
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT * FROM characters WHERE user_id=? AND guild_id=? ORDER BY created_at",
            (user_id, guild_id),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_character(character_id: int) -> None:
    """Delete a character; cascades to sheet, all fields, reviews, and pending review."""
    conn = connect_db()
    try:
        conn.execute("DELETE FROM characters WHERE character_id=?", (character_id,))
        conn.commit()
    finally:
        conn.close()


def get_characters_by_name_in_guild(guild_id: str, name: str) -> list:
    """
    Return all characters with an exact (case-insensitive) name match in a guild,
    across ALL users. Used for admin disambiguation when multiple users share a name.
    """
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT character_id, user_id, guild_id, name FROM characters"
            " WHERE guild_id = ? AND name = ? COLLATE NOCASE",
            (guild_id, name),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─── Sheets ───────────────────────────────────────────────────────────────────

def create_sheet(character_id: int) -> int:
    """Create a Draft sheet for a character. Returns sheet_id."""
    now = int(time.time())
    conn = connect_db()
    try:
        cur = conn.execute(
            "INSERT INTO sheets (character_id, status, created_at, updated_at) VALUES (?, 'Draft', ?, ?)",
            (character_id, now, now),
        )
        sheet_id = cur.lastrowid
        conn.commit()
        return sheet_id
    finally:
        conn.close()


def get_sheet(sheet_id: int) -> Optional[dict]:
    """Return a sheet row as a dict, or None."""
    conn = connect_db()
    try:
        row = conn.execute("SELECT * FROM sheets WHERE sheet_id=?", (sheet_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_sheet_by_character(character_id: int) -> Optional[dict]:
    """Return the most recent sheet for a character, or None."""
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT * FROM sheets WHERE character_id=? ORDER BY sheet_id DESC LIMIT 1",
            (character_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_approved_sheet(character_id: int) -> Optional[dict]:
    """Return the Approved sheet for a character, or None."""
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT * FROM sheets WHERE character_id=? AND status='Approved' ORDER BY sheet_id DESC LIMIT 1",
            (character_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_pending_sheet(character_id: int) -> Optional[dict]:
    """
    Return the active working sheet (Draft or Pending) for a character, or None.
    This is the sheet the user edits and submits.
    """
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT * FROM sheets WHERE character_id=? AND status IN ('Draft','Pending') ORDER BY sheet_id DESC LIMIT 1",
            (character_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_draft_from_approved(character_id: int) -> int:
    """
    Fork the approved sheet into a new Draft copy, copying all fields.
    Returns the new draft sheet_id.
    """
    now = int(time.time())
    conn = connect_db()
    try:
        approved = conn.execute(
            "SELECT * FROM sheets WHERE character_id=? AND status='Approved' ORDER BY sheet_id DESC LIMIT 1",
            (character_id,),
        ).fetchone()
        if not approved:
            raise ValueError("No approved sheet to fork from.")
        cur = conn.execute(
            "INSERT INTO sheets (character_id, status, created_at, updated_at) VALUES (?, 'Draft', ?, ?)",
            (character_id, now, now),
        )
        new_sheet_id = cur.lastrowid
        fields = conn.execute(
            "SELECT field_name, value, sort_order FROM sheet_fields WHERE sheet_id=?",
            (approved["sheet_id"],),
        ).fetchall()
        for field_name, value, sort_order in fields:
            conn.execute(
                "INSERT INTO sheet_fields (sheet_id, field_name, value, sort_order, updated_at) VALUES (?, ?, ?, ?, ?)",
                (new_sheet_id, field_name, value, sort_order, now),
            )
        conn.commit()
        return new_sheet_id
    finally:
        conn.close()


def promote_draft_to_approved(draft_sheet_id: int) -> None:
    """
    Atomically promote a Pending sheet to Approved:
    - Deletes the old Approved sheet for this character (and its fields via CASCADE)
    - Sets the draft/pending sheet status to Approved
    """
    now = int(time.time())
    conn = connect_db()
    try:
        draft = conn.execute(
            "SELECT character_id FROM sheets WHERE sheet_id=?", (draft_sheet_id,)
        ).fetchone()
        if not draft:
            raise ValueError("Sheet not found.")
        character_id = draft["character_id"]
        # Delete old approved sheet (fields cascade)
        conn.execute(
            "DELETE FROM sheets WHERE character_id=? AND status='Approved'",
            (character_id,),
        )
        conn.execute(
            "UPDATE sheets SET status='Approved', updated_at=? WHERE sheet_id=?",
            (now, draft_sheet_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_pending_sheets_for_guild(guild_id: str) -> list:
    """Return all Pending sheets in the guild with character + user info."""
    conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT c.character_id, c.user_id, c.name,
                   s.sheet_id, s.status, s.updated_at
            FROM   characters c
            JOIN   sheets s ON s.character_id = c.character_id
            WHERE  c.guild_id = ? AND s.status = 'Pending'
            ORDER  BY s.updated_at DESC
            """,
            (guild_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def set_sheet_status(sheet_id: int, status: str) -> None:
    now = int(time.time())
    conn = connect_db()
    try:
        conn.execute(
            "UPDATE sheets SET status=?, updated_at=? WHERE sheet_id=?",
            (status, now, sheet_id),
        )
        conn.commit()
    finally:
        conn.close()


# ─── Fields ───────────────────────────────────────────────────────────────────

def set_field(sheet_id: int, field_name: str, value: str, sort_order: Optional[int] = None) -> None:
    """
    Upsert a field value onto a sheet.
    If sort_order is None, the existing order is preserved (or 0 for new fields).
    """
    now = int(time.time())
    conn = connect_db()
    try:
        if sort_order is None:
            existing = conn.execute(
                "SELECT sort_order FROM sheet_fields WHERE sheet_id=? AND field_name=?",
                (sheet_id, field_name),
            ).fetchone()
            sort_order = existing[0] if existing else 0

        conn.execute(
            """
            INSERT INTO sheet_fields (sheet_id, field_name, value, sort_order, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(sheet_id, field_name) DO UPDATE SET
                value=excluded.value,
                sort_order=excluded.sort_order,
                updated_at=excluded.updated_at
            """,
            (sheet_id, field_name, value, sort_order, now),
        )
        conn.execute("UPDATE sheets SET updated_at=? WHERE sheet_id=?", (now, sheet_id))
        conn.commit()
    finally:
        conn.close()


def get_fields(sheet_id: int) -> list:
    """
    Return [(field_name, value, sort_order), ...] ordered by sort_order then field_name.
    """
    conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT field_name, value, sort_order
            FROM   sheet_fields
            WHERE  sheet_id=?
            ORDER  BY sort_order, field_name
            """,
            (sheet_id,),
        ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]
    finally:
        conn.close()


def delete_field(sheet_id: int, field_name: str) -> None:
    conn = connect_db()
    try:
        conn.execute(
            "DELETE FROM sheet_fields WHERE sheet_id=? AND field_name=?",
            (sheet_id, field_name),
        )
        conn.commit()
    finally:
        conn.close()


def apply_template(sheet_id: int, guild_id: str) -> None:
    """
    Add any missing guild template fields to the sheet with empty values.
    Fields that already exist are NOT overwritten.
    """
    now = int(time.time())
    conn = connect_db()
    try:
        template = conn.execute(
            "SELECT field_name, sort_order FROM guild_templates WHERE guild_id=? ORDER BY sort_order",
            (guild_id,),
        ).fetchall()
        for field_name, sort_order in template:
            conn.execute(
                """
                INSERT OR IGNORE INTO sheet_fields (sheet_id, field_name, value, sort_order, updated_at)
                VALUES (?, ?, '', ?, ?)
                """,
                (sheet_id, field_name, sort_order, now),
            )
        conn.commit()
    finally:
        conn.close()


# ─── Guild Templates ──────────────────────────────────────────────────────────

def add_template_field(guild_id: str, field_name: str, sort_order: int = 0, required: int = 0) -> None:
    """Add or update a field in the guild's sheet template."""
    conn = connect_db()
    try:
        conn.execute(
            """
            INSERT INTO guild_templates (guild_id, field_name, sort_order, required)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, field_name) DO UPDATE SET
                sort_order=excluded.sort_order,
                required=excluded.required
            """,
            (guild_id, field_name, sort_order, required),
        )
        conn.commit()
    finally:
        conn.close()


def get_template(guild_id: str) -> list:
    """Return [{'field_name', 'sort_order', 'required'}, ...] ordered by sort_order."""
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT field_name, sort_order, required FROM guild_templates WHERE guild_id=? ORDER BY sort_order",
            (guild_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def remove_template_field(guild_id: str, field_name: str) -> None:
    conn = connect_db()
    try:
        conn.execute(
            "DELETE FROM guild_templates WHERE guild_id=? AND field_name=?",
            (guild_id, field_name),
        )
        conn.commit()
    finally:
        conn.close()


def clear_template(guild_id: str) -> None:
    """Remove all template fields for a guild."""
    conn = connect_db()
    try:
        conn.execute("DELETE FROM guild_templates WHERE guild_id=?", (guild_id,))
        conn.commit()
    finally:
        conn.close()


# ─── Pending Reviews ──────────────────────────────────────────────────────────

def set_pending_review(sheet_id: int, channel_id: str, message_id: str) -> None:
    """Record the Discord message that holds active review buttons for a sheet."""
    now = int(time.time())
    conn = connect_db()
    try:
        conn.execute(
            """
            INSERT INTO pending_reviews (sheet_id, discord_channel_id, discord_message_id, submitted_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(sheet_id) DO UPDATE SET
                discord_channel_id=excluded.discord_channel_id,
                discord_message_id=excluded.discord_message_id,
                submitted_at=excluded.submitted_at
            """,
            (sheet_id, channel_id, message_id, now),
        )
        conn.commit()
    finally:
        conn.close()


def get_pending_review(sheet_id: int) -> Optional[dict]:
    """Return the pending review row for a sheet, or None."""
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT * FROM pending_reviews WHERE sheet_id=?", (sheet_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def clear_pending_review(sheet_id: int) -> None:
    """Remove the pending review record after an admin resolves it."""
    conn = connect_db()
    try:
        conn.execute("DELETE FROM pending_reviews WHERE sheet_id=?", (sheet_id,))
        conn.commit()
    finally:
        conn.close()


# ─── Sheet Reviews (audit trail) ──────────────────────────────────────────────

def record_review(
    sheet_id: int,
    reviewer_id: str,
    action: str,
    comment: str,
    discord_message_id: str = "",
) -> None:
    """Append an admin review action to the permanent audit trail."""
    now = int(time.time())
    conn = connect_db()
    try:
        conn.execute(
            """
            INSERT INTO sheet_reviews
                (sheet_id, reviewer_id, action, comment, discord_message_id, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (sheet_id, reviewer_id, action, comment, discord_message_id, now),
        )
        conn.commit()
    finally:
        conn.close()


# ─── Search / Listing ─────────────────────────────────────────────────────────

def search_characters(
    guild_id: str,
    name_query: Optional[str] = None,
    user_id: Optional[str] = None,
    status: Optional[str] = None,
) -> list:
    """
    Return joined character + sheet data for a guild.
    Optional filters: name substring, specific user_id, sheet status.
    """
    conn = connect_db()
    try:
        sql = """
            SELECT c.character_id, c.user_id, c.guild_id, c.name,
                   s.sheet_id, s.status, s.updated_at
            FROM   characters c
            JOIN   sheets s ON s.character_id = c.character_id
            WHERE  c.guild_id = ?
        """
        params: list = [guild_id]
        if name_query:
            sql += " AND c.name LIKE ? COLLATE NOCASE"
            params.append(f"%{name_query}%")
        if user_id:
            sql += " AND c.user_id = ?"
            params.append(user_id)
        if status:
            sql += " AND s.status = ?"
            params.append(status)
        sql += " ORDER BY c.name COLLATE NOCASE"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_sheets_by_user(user_id: str, guild_id: str, status: Optional[str] = None) -> list:
    """
    Return character + sheet rows for a user, optionally filtered by status.
    Returns ALL sheets per character (both Approved and Draft/Pending).
    """
    conn = connect_db()
    try:
        sql = """
            SELECT c.character_id, c.name, s.sheet_id, s.status, s.created_at, s.updated_at
            FROM   characters c
            JOIN   sheets s ON s.character_id = c.character_id
            WHERE  c.user_id=? AND c.guild_id=?
        """
        params: list = [user_id, guild_id]
        if status:
            sql += " AND s.status=?"
            params.append(status)
        sql += " ORDER BY c.name COLLATE NOCASE, s.status"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─── Settings.db helpers ──────────────────────────────────────────────────────

def get_channel_ids(guild_id: str) -> dict:
    """Return {'admin': int|None, 'member': int|None} from Settings.db Server table."""
    try:
        conn = sqlite3.connect(SETTINGS_DB, timeout=5)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT admin_channel_id, member_channel_id FROM Server WHERE guild_id=?",
            (guild_id,),
        ).fetchone()
        conn.close()
        if row:
            return {"admin": row["admin_channel_id"], "member": row["member_channel_id"]}
    except Exception:
        pass
    return {"admin": None, "member": None}

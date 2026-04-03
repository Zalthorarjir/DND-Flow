"""
Local Admin Dashboard for Discord Bot
Can be exposed online when the port is forwarded or proxied
Offline backup mode: localhost-only, always-admin, no Discord login
"""

import os
import sqlite3
import json
import re
import secrets
import hmac
import time
import logging
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file, abort, redirect, g, session, url_for
from datetime import datetime, timedelta, timezone
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib import parse as urllib_parse

from dotenv import dotenv_values
from werkzeug.middleware.proxy_fix import ProxyFix

ONLINE_WEB_SERVER_DIR = Path(__file__).parent
ONLINE_WEB_SERVER_ENV_PATH = ONLINE_WEB_SERVER_DIR / ".env"
ONLINE_WEB_SERVER_ENV = dotenv_values(ONLINE_WEB_SERVER_ENV_PATH) if ONLINE_WEB_SERVER_ENV_PATH.exists() else {}

app = Flask(__name__)
app.secret_key = str(ONLINE_WEB_SERVER_ENV.get('FLASK_SECRET_KEY') or secrets.token_hex(32))

VISIBLE_SERVER_OPTIONS_CACHE_TTL_SECONDS = int(
    str(ONLINE_WEB_SERVER_ENV.get('VISIBLE_SERVER_OPTIONS_CACHE_TTL_SECONDS') or '90').strip() or '90'
)
DYNAMIC_SERVER_OPTIONS_CACHE_TTL_SECONDS = int(
    str(ONLINE_WEB_SERVER_ENV.get('DYNAMIC_SERVER_OPTIONS_CACHE_TTL_SECONDS') or '30').strip() or '30'
)

_VISIBLE_SERVER_OPTIONS_MEMORY_CACHE = {}
_DYNAMIC_SERVER_OPTIONS_MEMORY_CACHE = {
    'expires_at': 0,
    'data': None,
}
USERS_LIST_CACHE_TTL_SECONDS = int(
    str(ONLINE_WEB_SERVER_ENV.get('USERS_LIST_CACHE_TTL_SECONDS') or '8').strip() or '8'
)
_USERS_LIST_MEMORY_CACHE = {}
DISCORD_BASIC_PROFILE_CACHE_TTL_SECONDS = int(
    str(ONLINE_WEB_SERVER_ENV.get('DISCORD_BASIC_PROFILE_CACHE_TTL_SECONDS') or '600').strip() or '600'
)
_DISCORD_BASIC_PROFILE_MEMORY_CACHE = {}


def utc_now():
    """Return a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def utc_now_iso_z():
    """Return current UTC timestamp as ISO-8601 with Z suffix."""
    return utc_now().isoformat(timespec='seconds').replace('+00:00', 'Z')

DASHBOARD_TABS = {
    'overview',
    'server',
    'server_shop',
    'shop',
    'jobs',
    'items',
    'settings',
    'users',
    'audit',
}

ROLE_ADMIN = 'Admin'
ROLE_MEMBER = 'Member'
ROLE_UNASSIGNED = 'Unassigned'

ROLE_ALLOWED_TABS = {
    ROLE_UNASSIGNED: {'overview', 'server_shop'},
    ROLE_MEMBER: {'users', 'server_shop'},
    ROLE_ADMIN: set(DASHBOARD_TABS),
}

OFFLINE_MODE = True
OFFLINE_ADMIN_USER = {
    'id': 'offline-admin',
    'username': 'Offline Admin',
    'display_name': 'Offline Admin',
    'avatar_url': 'https://cdn.discordapp.com/embed/avatars/0.png',
}

# Paths to bot databases
BOT_DIR = Path(__file__).parent.parent / "Discord_Bot"
BOT_ENV_PATH = BOT_DIR / ".env"
SETTINGS_DB = BOT_DIR / "databases" / "Settings.db"
SHEETS_DB = BOT_DIR / "databases" / "Sheets.db"
AUDIT_DB = BOT_DIR / "databases" / "Audit.db"
SHOP_DB = BOT_DIR / "databases" / "Shop.db"
ECONOMY_DB = BOT_DIR / "databases" / "Economy.db"
INVENTORY_DB = BOT_DIR / "databases" / "Inventory.db"
# Item catalog is stored in Shop.db (table: items) in the current bot schema.
ITEMS_DB = SHOP_DB
# Death and combat settings share Combat.db in the current bot schema.
COMBAT_DB = BOT_DIR / "databases" / "Combat.db"
DEATHCOOLDOWN_DB = COMBAT_DB
CURRENCY_DIR = BOT_DIR / "databases" / "Currency"
ITEMS_DIR = BOT_DIR / "databases" / "Items"
USERS_DIR = BOT_DIR / "databases" / "Users"
TEMPLATES_DIR = Path(__file__).parent / "templates"
SERVER_ICON_CACHE_DIR = ONLINE_WEB_SERVER_DIR / "static" / "server_icons"


def ensure_settings_schema():
    """Ensure Settings.db tables required by dashboard routes exist."""
    SERVER_ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(SETTINGS_DB))
    try:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS Server (
            guild_id INTEGER PRIMARY KEY,
            admin_role_id INTEGER,
            admin_channel_id INTEGER,
            member_role_id INTEGER,
            member_channel_id INTEGER
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS ServerCache (
            guild_id TEXT PRIMARY KEY,
            guild_name TEXT,
            icon_hash TEXT,
            icon_file TEXT,
            updated_at INTEGER NOT NULL
        )''')
        c.execute('PRAGMA table_info(ServerCache)')
        cache_columns = {str(row[1]) for row in c.fetchall()}
        if 'icon_file' not in cache_columns:
            c.execute('ALTER TABLE ServerCache ADD COLUMN icon_file TEXT')
        conn.commit()
    finally:
        conn.close()


def ensure_sheet_templates_schema():
    """Ensure Sheets.db template table exists (matches bot sheet_storage schema)."""
    conn = sqlite3.connect(str(SHEETS_DB))
    try:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS guild_templates (
            template_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id    TEXT    NOT NULL,
            field_name  TEXT    NOT NULL,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            required    INTEGER NOT NULL DEFAULT 0,
            UNIQUE (guild_id, field_name)
        )''')
        conn.commit()
    finally:
        conn.close()


def ensure_sheet_storage_schema():
    """Ensure core Sheets.db tables used by the redesigned bot schema exist."""
    conn = sqlite3.connect(str(SHEETS_DB))
    try:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS characters (
            character_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      TEXT    NOT NULL,
            guild_id     TEXT    NOT NULL,
            name         TEXT    NOT NULL,
            created_at   INTEGER NOT NULL,
            UNIQUE (user_id, guild_id, name)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS sheets (
            sheet_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id INTEGER NOT NULL,
            status       TEXT    NOT NULL DEFAULT 'Draft',
            created_at   INTEGER NOT NULL,
            updated_at   INTEGER NOT NULL
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS sheet_fields (
            field_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            sheet_id   INTEGER NOT NULL,
            field_name TEXT    NOT NULL,
            value      TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL,
            UNIQUE (sheet_id, field_name)
        )''')
        conn.commit()
    finally:
        conn.close()


def ensure_sheet_index_schema():
    """Ensure Settings.db SheetIndex has required columns for web-to-storage mapping."""
    conn = sqlite3.connect(str(SETTINGS_DB))
    try:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS SheetIndex (
            user_id TEXT NOT NULL,
            guild_id INTEGER,
            sheet_id TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            review_channel_id INTEGER,
            review_message_id INTEGER,
            storage_sheet_id INTEGER,
            PRIMARY KEY (user_id, sheet_id)
        )''')
        c.execute('PRAGMA table_info(SheetIndex)')
        columns = {str(row[1]) for row in c.fetchall()}
        if 'review_channel_id' not in columns:
            c.execute('ALTER TABLE SheetIndex ADD COLUMN review_channel_id INTEGER')
        if 'review_message_id' not in columns:
            c.execute('ALTER TABLE SheetIndex ADD COLUMN review_message_id INTEGER')
        if 'storage_sheet_id' not in columns:
            c.execute('ALTER TABLE SheetIndex ADD COLUMN storage_sheet_id INTEGER')
        conn.commit()
    finally:
        conn.close()


def _get_table_columns(conn, table_name):
    """Return the column names for a SQLite table."""
    try:
        rows = conn.execute(f'PRAGMA table_info({table_name})').fetchall()
    except sqlite3.DatabaseError:
        return set()
    return {str(row[1]) for row in rows}


def _add_scope_guild_id(target_ids, seen_ids, raw_guild_id):
    guild_id = str(raw_guild_id or '').strip()
    if not _SNOWFLAKE_RE.fullmatch(guild_id):
        return
    if guild_id in seen_ids:
        return
    seen_ids.add(guild_id)
    target_ids.append(guild_id)


def get_dashboard_scope_guild_ids(preferred_guild_id=None):
    """Return guild ids to seed per-server migrations with current known servers."""
    target_ids = []
    seen_ids = set()
    _add_scope_guild_id(target_ids, seen_ids, preferred_guild_id)

    if SETTINGS_DB.exists():
        ensure_settings_schema()
        conn = sqlite3.connect(str(SETTINGS_DB))
        try:
            for row in conn.execute('SELECT guild_id FROM Server ORDER BY guild_id').fetchall() or []:
                _add_scope_guild_id(target_ids, seen_ids, row[0] if row else None)
        finally:
            conn.close()

    for guild in get_live_bot_guilds() or []:
        _add_scope_guild_id(target_ids, seen_ids, (guild or {}).get('id'))

    return target_ids


def _ensure_scoped_shop_table(scope_guild_ids):
    os.makedirs(os.path.dirname(SHOP_DB), exist_ok=True)
    conn = sqlite3.connect(str(SHOP_DB))
    try:
        columns = _get_table_columns(conn, 'shop')
        if not columns:
            conn.execute(
                '''CREATE TABLE IF NOT EXISTS shop (
                    guild_id TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    price INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, item_name)
                )'''
            )
        elif 'guild_id' not in columns:
            legacy_rows = conn.execute('SELECT item_name, price FROM shop').fetchall() or []
            conn.execute('ALTER TABLE shop RENAME TO shop_legacy')
            conn.execute(
                '''CREATE TABLE shop (
                    guild_id TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    price INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, item_name)
                )'''
            )
            for guild_id in scope_guild_ids:
                for item_name, price in legacy_rows:
                    conn.execute(
                        'INSERT OR REPLACE INTO shop (guild_id, item_name, price) VALUES (?, ?, ?)',
                        (guild_id, item_name, price),
                    )
            conn.execute('DROP TABLE shop_legacy')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_shop_guild_id ON shop(guild_id)')
        conn.commit()
    finally:
        conn.close()


def _ensure_scoped_items_table(scope_guild_ids):
    os.makedirs(os.path.dirname(ITEMS_DB), exist_ok=True)
    conn = sqlite3.connect(str(ITEMS_DB))
    try:
        columns = _get_table_columns(conn, 'items')
        if not columns:
            conn.execute(
                '''CREATE TABLE IF NOT EXISTS items (
                    guild_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    consumable TEXT NOT NULL CHECK (consumable IN ('Yes', 'No')),
                    image TEXT,
                    description TEXT,
                    PRIMARY KEY (guild_id, name)
                )'''
            )
        elif 'guild_id' not in columns:
            legacy_rows = conn.execute('SELECT name, consumable, image, description FROM items').fetchall() or []
            conn.execute('ALTER TABLE items RENAME TO items_legacy')
            conn.execute(
                '''CREATE TABLE items (
                    guild_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    consumable TEXT NOT NULL CHECK (consumable IN ('Yes', 'No')),
                    image TEXT,
                    description TEXT,
                    PRIMARY KEY (guild_id, name)
                )'''
            )
            for guild_id in scope_guild_ids:
                for name, consumable, image, description in legacy_rows:
                    conn.execute(
                        '''INSERT OR REPLACE INTO items (guild_id, name, consumable, image, description)
                           VALUES (?, ?, ?, ?, ?)''',
                        (guild_id, name, consumable, image, description),
                    )
            conn.execute('DROP TABLE items_legacy')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_items_guild_id ON items(guild_id)')
        conn.commit()
    finally:
        conn.close()


def _ensure_scoped_jobs_table(scope_guild_ids):
    os.makedirs(os.path.dirname(ECONOMY_DB), exist_ok=True)
    conn = sqlite3.connect(str(ECONOMY_DB))
    try:
        columns = _get_table_columns(conn, 'jobs')
        if not columns:
            conn.execute(
                '''CREATE TABLE IF NOT EXISTS jobs (
                    guild_id TEXT NOT NULL,
                    job_name TEXT NOT NULL,
                    payment REAL,
                    PRIMARY KEY (guild_id, job_name)
                )'''
            )
        elif 'guild_id' not in columns:
            legacy_rows = conn.execute('SELECT job_name, payment FROM jobs').fetchall() or []
            conn.execute('ALTER TABLE jobs RENAME TO jobs_legacy')
            conn.execute(
                '''CREATE TABLE jobs (
                    guild_id TEXT NOT NULL,
                    job_name TEXT NOT NULL,
                    payment REAL,
                    PRIMARY KEY (guild_id, job_name)
                )'''
            )
            for guild_id in scope_guild_ids:
                for job_name, payment in legacy_rows:
                    conn.execute(
                        'INSERT OR REPLACE INTO jobs (guild_id, job_name, payment) VALUES (?, ?, ?)',
                        (guild_id, job_name, payment),
                    )
            conn.execute('DROP TABLE jobs_legacy')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_jobs_guild_id ON jobs(guild_id)')
        conn.commit()
    finally:
        conn.close()


def _ensure_scoped_work_cooldown_table(scope_guild_ids):
    os.makedirs(os.path.dirname(SETTINGS_DB), exist_ok=True)
    conn = sqlite3.connect(str(SETTINGS_DB))
    try:
        columns = _get_table_columns(conn, 'WorkCooldown')
        if not columns:
            conn.execute(
                '''CREATE TABLE IF NOT EXISTS WorkCooldown (
                    guild_id TEXT PRIMARY KEY,
                    days INTEGER
                )'''
            )
        elif 'guild_id' not in columns:
            legacy_rows = conn.execute('SELECT days FROM WorkCooldown').fetchall() or []
            legacy_days = int((legacy_rows[-1][0] if legacy_rows else 0) or 0)
            conn.execute('ALTER TABLE WorkCooldown RENAME TO WorkCooldown_legacy')
            conn.execute(
                '''CREATE TABLE WorkCooldown (
                    guild_id TEXT PRIMARY KEY,
                    days INTEGER
                )'''
            )
            for guild_id in scope_guild_ids:
                conn.execute(
                    'INSERT OR REPLACE INTO WorkCooldown (guild_id, days) VALUES (?, ?)',
                    (guild_id, legacy_days),
                )
            conn.execute('DROP TABLE WorkCooldown_legacy')
        conn.commit()
    finally:
        conn.close()


def _ensure_scoped_death_settings_table(scope_guild_ids):
    os.makedirs(os.path.dirname(DEATHCOOLDOWN_DB), exist_ok=True)
    conn = sqlite3.connect(str(DEATHCOOLDOWN_DB))
    try:
        columns = _get_table_columns(conn, 'GlobalSettings')
        if not columns:
            conn.execute(
                '''CREATE TABLE IF NOT EXISTS GlobalSettings (
                    guild_id TEXT PRIMARY KEY,
                    cooldown INTEGER DEFAULT 0,
                    infinite INTEGER DEFAULT 0
                )'''
            )
        elif 'guild_id' not in columns:
            legacy_rows = conn.execute('SELECT cooldown, infinite FROM GlobalSettings').fetchall() or []
            legacy_cooldown = int((legacy_rows[-1][0] if legacy_rows else 0) or 0)
            legacy_infinite = int((legacy_rows[-1][1] if legacy_rows else 0) or 0)
            conn.execute('ALTER TABLE GlobalSettings RENAME TO GlobalSettings_legacy')
            conn.execute(
                '''CREATE TABLE GlobalSettings (
                    guild_id TEXT PRIMARY KEY,
                    cooldown INTEGER DEFAULT 0,
                    infinite INTEGER DEFAULT 0
                )'''
            )
            for guild_id in scope_guild_ids:
                conn.execute(
                    'INSERT OR REPLACE INTO GlobalSettings (guild_id, cooldown, infinite) VALUES (?, ?, ?)',
                    (guild_id, legacy_cooldown, legacy_infinite),
                )
            conn.execute('DROP TABLE GlobalSettings_legacy')
        conn.commit()
    finally:
        conn.close()


def _ensure_scoped_combat_rules_table(scope_guild_ids):
    os.makedirs(os.path.dirname(COMBAT_DB), exist_ok=True)
    conn = sqlite3.connect(str(COMBAT_DB))
    try:
        columns = _get_table_columns(conn, 'Rules')
        if not columns:
            conn.execute(
                '''CREATE TABLE IF NOT EXISTS Rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    hitchance REAL,
                    missed1 REAL,
                    missed2 REAL,
                    missed3 REAL
                )'''
            )
        elif 'guild_id' not in columns:
            legacy_rows = conn.execute(
                'SELECT hitchance, missed1, missed2, missed3 FROM Rules ORDER BY id ASC'
            ).fetchall() or []
            conn.execute('ALTER TABLE Rules RENAME TO Rules_legacy')
            conn.execute(
                '''CREATE TABLE Rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL,
                    hitchance REAL,
                    missed1 REAL,
                    missed2 REAL,
                    missed3 REAL
                )'''
            )
            for guild_id in scope_guild_ids:
                for hitchance, missed1, missed2, missed3 in legacy_rows:
                    conn.execute(
                        '''INSERT INTO Rules (guild_id, hitchance, missed1, missed2, missed3)
                           VALUES (?, ?, ?, ?, ?)''',
                        (guild_id, hitchance, missed1, missed2, missed3),
                    )
            conn.execute('DROP TABLE Rules_legacy')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_rules_guild_id_id ON Rules(guild_id, id DESC)')
        conn.commit()
    finally:
        conn.close()


def ensure_server_scoped_dashboard_schema(preferred_guild_id=None):
    """Ensure dashboard-managed data tables are stored per guild."""
    scope_guild_ids = get_dashboard_scope_guild_ids(preferred_guild_id)
    _ensure_scoped_shop_table(scope_guild_ids)
    _ensure_scoped_items_table(scope_guild_ids)
    _ensure_scoped_jobs_table(scope_guild_ids)
    _ensure_scoped_work_cooldown_table(scope_guild_ids)
    _ensure_scoped_death_settings_table(scope_guild_ids)
    _ensure_scoped_combat_rules_table(scope_guild_ids)


def delete_item_image_if_unreferenced(image_name):
    """Delete an item image only when no remaining item rows reference it."""
    normalized = str(image_name or '').strip()
    if not normalized or not ITEMS_DB.exists():
        return

    conn = sqlite3.connect(str(ITEMS_DB))
    try:
        row = conn.execute('SELECT 1 FROM items WHERE image=? LIMIT 1', (normalized,)).fetchone()
    finally:
        conn.close()

    if row:
        return

    image_path = os.path.join(str(ITEMS_DIR), normalized)
    if os.path.exists(image_path):
        os.remove(image_path)


def _resolve_storage_sheet_id(user_id, external_sheet_id):
    """Resolve web-facing sheet_id to Sheets.db integer sheet_id."""
    ensure_sheet_storage_schema()
    ensure_sheet_index_schema()

    # First preference: explicit mapping in SheetIndex.
    conn = get_db_connection(SETTINGS_DB)
    c = conn.cursor()
    c.execute(
        'SELECT storage_sheet_id, sheet_name FROM SheetIndex WHERE user_id=? AND sheet_id=? LIMIT 1',
        (str(user_id), str(external_sheet_id)),
    )
    idx_row = c.fetchone()
    conn.close()

    mapped_storage_id = int(idx_row.get('storage_sheet_id') or 0) if idx_row else 0
    if mapped_storage_id:
        return mapped_storage_id

    # If the external ID is already numeric, allow direct lookup.
    candidate_numeric = str(external_sheet_id or '').strip()
    if candidate_numeric.isdigit():
        sid = int(candidate_numeric)
        conn = sqlite3.connect(str(SHEETS_DB))
        try:
            row = conn.execute(
                '''SELECT s.sheet_id
                   FROM sheets s
                   JOIN characters c ON c.character_id=s.character_id
                   WHERE s.sheet_id=? AND c.user_id=?
                   LIMIT 1''',
                (sid, str(user_id)),
            ).fetchone()
            if row:
                return int(row[0])
        finally:
            conn.close()

    # Last attempt: map by indexed sheet name for this user.
    indexed_name = str((idx_row or {}).get('sheet_name') or '').strip()
    if indexed_name:
        conn = sqlite3.connect(str(SHEETS_DB))
        try:
            row = conn.execute(
                '''SELECT s.sheet_id
                   FROM sheets s
                   JOIN characters c ON c.character_id=s.character_id
                   WHERE c.user_id=? AND c.name=?
                   ORDER BY s.sheet_id DESC
                   LIMIT 1''',
                (str(user_id), indexed_name),
            ).fetchone()
            if row:
                resolved_sid = int(row[0])
                conn_settings = sqlite3.connect(str(SETTINGS_DB))
                try:
                    conn_settings.execute(
                        'UPDATE SheetIndex SET storage_sheet_id=? WHERE user_id=? AND sheet_id=?',
                        (resolved_sid, str(user_id), str(external_sheet_id)),
                    )
                    conn_settings.commit()
                finally:
                    conn_settings.close()
                return resolved_sid
        finally:
            conn.close()

    return None


def list_guild_template_fields(guild_id: int) -> list[str]:
    """Return ordered sheet template fields for one guild."""
    ensure_sheet_templates_schema()
    conn = sqlite3.connect(str(SHEETS_DB))
    try:
        c = conn.cursor()
        c.execute(
            'SELECT field_name FROM guild_templates WHERE guild_id=? ORDER BY sort_order ASC, field_name COLLATE NOCASE ASC',
            (str(guild_id),),
        )
        return [str(row[0]) for row in c.fetchall() if row and row[0]]
    finally:
        conn.close()


def add_guild_template_field(guild_id: int, field_name: str) -> None:
    """Insert a field in guild template with stable append ordering."""
    ensure_sheet_templates_schema()
    conn = sqlite3.connect(str(SHEETS_DB))
    try:
        c = conn.cursor()
        c.execute('SELECT COALESCE(MAX(sort_order), -1) + 1 FROM guild_templates WHERE guild_id=?', (str(guild_id),))
        next_order = int((c.fetchone() or [0])[0] or 0)
        c.execute(
            'INSERT INTO guild_templates (guild_id, field_name, sort_order, required) VALUES (?, ?, ?, 0)',
            (str(guild_id), field_name, next_order),
        )
        conn.commit()
    finally:
        conn.close()


def remove_guild_template_field(guild_id: int, field_name: str) -> None:
    """Delete a field from a guild template."""
    ensure_sheet_templates_schema()
    conn = sqlite3.connect(str(SHEETS_DB))
    try:
        c = conn.cursor()
        c.execute('DELETE FROM guild_templates WHERE guild_id=? AND field_name=?', (str(guild_id), field_name))
        conn.commit()
    finally:
        conn.close()


def clear_guild_template_fields(guild_id: int | None = None) -> None:
    """Delete template fields for one guild, or all when guild_id is None."""
    ensure_sheet_templates_schema()
    conn = sqlite3.connect(str(SHEETS_DB))
    try:
        c = conn.cursor()
        if guild_id is None:
            c.execute('DELETE FROM guild_templates')
        else:
            c.execute('DELETE FROM guild_templates WHERE guild_id=?', (str(guild_id),))
        conn.commit()
    finally:
        conn.close()


def list_all_template_field_names() -> list[str]:
    """Return unique field names configured across all guild templates."""
    ensure_sheet_templates_schema()
    conn = sqlite3.connect(str(SHEETS_DB))
    try:
        c = conn.cursor()
        c.execute(
            'SELECT DISTINCT field_name FROM guild_templates WHERE field_name IS NOT NULL AND TRIM(field_name) != "" ORDER BY field_name COLLATE NOCASE'
        )
        return [str(row[0]).strip() for row in c.fetchall() if row and str(row[0]).strip()]
    finally:
        conn.close()


def get_online_web_server_setting(name, default=None):
    """Read Online_Web_Server settings from Online_Web_Server/.env with legacy fallback."""
    value = ONLINE_WEB_SERVER_ENV.get(name)
    if value is None and str(name).startswith('ONLINE_WEB_SERVER_'):
        legacy_name = str(name).replace('ONLINE_WEB_SERVER_', 'USER_SERVER_', 1)
        value = ONLINE_WEB_SERVER_ENV.get(legacy_name)
    elif value is None and str(name).startswith('USER_SERVER_'):
        new_name = str(name).replace('USER_SERVER_', 'ONLINE_WEB_SERVER_', 1)
        value = ONLINE_WEB_SERVER_ENV.get(new_name)
    if value is None:
        return default
    value = str(value).strip()
    return value or default


def get_user_server_setting(name, default=None):
    """Backward-compatible alias for legacy naming in existing call sites."""
    return get_online_web_server_setting(name, default)


def get_user_server_bool_setting(name, default=False):
    """Parse boolean-like values from Online_Web_Server/.env."""
    value = get_user_server_setting(name)
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def get_user_server_int_setting(name, default):
    """Parse integer values from Online_Web_Server/.env."""
    value = get_user_server_setting(name)
    if value is None:
        return default
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def get_discord_oauth_settings():
    """Return Discord OAuth settings for Online_Web_Server."""
    return {
        'client_id': get_user_server_setting('DISCORD_CLIENT_ID'),
        'client_secret': get_user_server_setting('DISCORD_CLIENT_SECRET'),
        'redirect_uri': get_user_server_setting('DISCORD_REDIRECT_URI'),
        'scope': get_user_server_setting('DISCORD_OAUTH_SCOPE', 'identify'),
    }


def get_user_server_bind_host():
    """Return the host interface the offline web server should bind to."""
    return get_online_web_server_setting('ONLINE_WEB_SERVER_HOST', '127.0.0.1')


def get_user_server_port():
    """Return the configured offline web server port."""
    return get_user_server_int_setting('ONLINE_WEB_SERVER_PORT', 5002)


def get_public_base_url():
    """Return the externally visible base URL for startup messaging."""
    configured = get_user_server_setting('PUBLIC_BASE_URL')
    if configured:
        return configured.rstrip('/')

    redirect_uri = get_discord_oauth_settings().get('redirect_uri') or ''
    if redirect_uri:
        parsed = urllib_parse.urlsplit(redirect_uri)
        if parsed.scheme and parsed.netloc:
            return f'{parsed.scheme}://{parsed.netloc}'

    host = get_user_server_bind_host()
    port = get_user_server_port()
    if host == '0.0.0.0':
        return f'http://127.0.0.1:{port}'
    return f'http://{host}:{port}'


def get_ssl_cert_file():
    """Return the configured TLS certificate path if present."""
    return get_online_web_server_setting('ONLINE_WEB_SERVER_SSL_CERT')


def get_ssl_key_file():
    """Return the configured TLS private key path if present."""
    return get_online_web_server_setting('ONLINE_WEB_SERVER_SSL_KEY')


def get_ssl_context_config():
    """Build an ssl_context tuple for Flask when cert and key files exist."""
    cert_file = get_ssl_cert_file()
    key_file = get_ssl_key_file()
    if not cert_file or not key_file:
        return None

    cert_path = Path(cert_file)
    key_path = Path(key_file)
    if not cert_path.is_file() or not key_path.is_file():
        return None
    return (str(cert_path), str(key_path))


def is_secure_public_url():
    """Return True when the configured public URL is HTTPS."""
    redirect_uri = get_discord_oauth_settings().get('redirect_uri') or ''
    public_base_url = get_user_server_setting('PUBLIC_BASE_URL') or ''
    candidate = str(public_base_url or redirect_uri).strip().lower()
    return candidate.startswith('https://')


app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = is_secure_public_url()
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['PREFERRED_URL_SCHEME'] = 'https' if is_secure_public_url() else 'http'

MAX_ITEM_IMAGE_UPLOAD_MB = max(get_user_server_int_setting('MAX_ITEM_IMAGE_UPLOAD_MB', 8), 1)
MAX_ITEM_IMAGE_UPLOAD_BYTES = MAX_ITEM_IMAGE_UPLOAD_MB * 1024 * 1024
ALLOWED_ITEM_IMAGE_MIME_TYPES = {
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp',
}
ALLOWED_ITEM_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
ALLOWED_ITEM_IMAGE_SIGNATURES = {'jpeg', 'png', 'gif', 'webp'}
app.config['MAX_CONTENT_LENGTH'] = MAX_ITEM_IMAGE_UPLOAD_BYTES

if get_user_server_bool_setting('TRUST_PROXY_HEADERS', False):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)


def is_discord_oauth_configured():
    """Return True when Discord OAuth credentials are configured."""
    config = get_discord_oauth_settings()
    return bool(config['client_id'] and config['client_secret'] and config['redirect_uri'])


def get_discord_bot_token():
    """Resolve the bot token only from Discord_Bot/.env."""
    values = dotenv_values(BOT_ENV_PATH)
    token = values.get('DISCORD_TOKEN')
    return str(token).strip() if token else None

def dict_factory(cursor, row):
    """Convert database rows to dictionaries"""
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def get_db_connection(db_path):
    """Get database connection with dict factory"""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = dict_factory
    return conn


def current_discord_user():
    """Return the authenticated Discord user stored in session."""
    if OFFLINE_MODE:
        return dict(OFFLINE_ADMIN_USER)
    user = session.get('discord_user')
    return user if isinstance(user, dict) else None


def get_or_create_csrf_token():
    """Return session CSRF token, creating one when missing."""
    token = str(session.get('csrf_token') or '').strip()
    if not token:
        token = secrets.token_urlsafe(32)
        session['csrf_token'] = token
    return token


def is_valid_csrf_token(candidate):
    """Constant-time comparison for CSRF token validation."""
    expected = str(session.get('csrf_token') or '').strip()
    provided = str(candidate or '').strip()
    return bool(expected) and bool(provided) and hmac.compare_digest(expected, provided)


def format_session_user(user_payload):
    """Normalize Discord OAuth profile data for session storage."""
    user_id = str(user_payload.get('id') or '').strip()
    username = str(user_payload.get('username') or 'Discord User').strip() or 'Discord User'
    display_name = str(user_payload.get('global_name') or username).strip() or username
    avatar_hash = user_payload.get('avatar')
    avatar_url = f'https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=128' if user_id and avatar_hash else get_default_avatar_url(user_id)
    return {
        'id': user_id,
        'username': username,
        'display_name': display_name,
        'avatar_url': avatar_url,
    }


def current_audit_actor():
    """Build a readable audit actor label for the logged-in Discord user."""
    user = current_discord_user()
    if not user:
        return None
    display_name = str(user.get('display_name') or user.get('username') or 'Discord User').strip() or 'Discord User'
    user_id = str(user.get('id') or '').strip()
    return f'{display_name} ({user_id})' if user_id else display_name


def normalize_next_path(raw_value):
    """Restrict post-login redirects to local application paths."""
    candidate = str(raw_value or '').strip()
    if not candidate:
        return '/overview'

    parsed = urllib_parse.urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return '/overview'

    path = parsed.path or '/overview'
    if not path.startswith('/'):
        return '/overview'
    if path in {'/login', '/callback', '/logout'}:
        return '/overview'

    return f"{path}?{parsed.query}" if parsed.query else path


def build_discord_login_url(state_value):
    """Create the Discord OAuth authorize URL."""
    oauth = get_discord_oauth_settings()
    query = urllib_parse.urlencode(
        {
            'client_id': oauth['client_id'],
            'redirect_uri': oauth['redirect_uri'],
            'response_type': 'code',
            'scope': oauth['scope'],
            'state': state_value,
            'prompt': 'consent',
        }
    )
    return f'https://discord.com/oauth2/authorize?{query}'


def exchange_discord_code(code_value):
    """Exchange a Discord OAuth code for an access token."""
    oauth = get_discord_oauth_settings()
    token_url = 'https://discord.com/api/oauth2/token'
    payload = urllib_parse.urlencode(
        {
            'client_id': oauth['client_id'],
            'client_secret': oauth['client_secret'],
            'grant_type': 'authorization_code',
            'code': code_value,
            'redirect_uri': oauth['redirect_uri'],
        }
    ).encode('utf-8')
    request_obj = urllib_request.Request(
        token_url,
        data=payload,
        headers={
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            # Avoid default Python-urllib signature being blocked by Cloudflare.
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Origin': 'https://discord.com',
            'Referer': 'https://discord.com/oauth2/authorize',
        },
        method='POST',
    )
    with urllib_request.urlopen(request_obj, timeout=10) as response:
        return json.loads(response.read().decode('utf-8'))


def fetch_discord_oauth_user(access_token):
    """Fetch the Discord profile for an authenticated OAuth user."""
    request_obj = urllib_request.Request(
        'https://discord.com/api/users/@me',
        headers={
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'User-Agent': 'DNDFlowUserServer/1.0',
        },
    )
    with urllib_request.urlopen(request_obj, timeout=10) as response:
        return json.loads(response.read().decode('utf-8'))


@app.context_processor
def inject_auth_user():
    """Expose the current Discord user to templates."""
    role = current_session_role()
    permissions = {
        'can_edit_inventory': role_is_admin(role),
        'can_edit_own_sheets': role_is_member_or_admin(role),
        'can_delete_other_sheets': role_is_admin(role),
        'can_manage_server_fields': role_is_admin(role),
        'can_edit_server_ids': role_is_admin(role),
        'can_change_sheet_status': role_is_admin(role),
    }
    return {
        'current_user': current_discord_user(),
        'session_role': role,
        'allowed_tabs': get_allowed_dashboard_tabs(role),
        'dashboard_permissions': permissions,
        'csrf_token': get_or_create_csrf_token(),
    }


def _json_dump_limited(value, max_len=1500):
    """Serialize JSON payload while keeping rows compact."""
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        raw = str(value)
    return raw[:max_len]


def api_error_response(message='Request failed.', status=400, exc=None):
    """Return a sanitized API error while preserving server-side diagnostics."""
    if exc is not None:
        app.logger.exception(
            'API error status=%s method=%s path=%s message=%s exc=%s',
            status,
            request.method,
            request.path,
            message,
            exc.__class__.__name__,
        )
    return jsonify({'error': message}), status


def _create_audit_log_schema(conn):
    """Ensure the dedicated audit database has the expected table and indexes."""
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS AuditLog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            actor TEXT NOT NULL,
            source TEXT NOT NULL,
            method TEXT NOT NULL,
            route TEXT NOT NULL,
            action TEXT NOT NULL,
            request_details TEXT,
            response_status INTEGER NOT NULL
        )'''
    )
    conn.execute('CREATE INDEX IF NOT EXISTS idx_auditlog_created_at ON AuditLog(created_at)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_auditlog_actor ON AuditLog(actor)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_auditlog_route ON AuditLog(route)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_auditlog_source ON AuditLog(source)')


def _migrate_legacy_audit_log():
    """Move legacy audit rows out of Settings.db into the dedicated audit database."""
    if not SETTINGS_DB.exists():
        return

    legacy_conn = sqlite3.connect(str(SETTINGS_DB))
    try:
        has_legacy_table = legacy_conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='AuditLog'"
        ).fetchone()
        if not has_legacy_table:
            return

        legacy_rows = legacy_conn.execute(
            '''SELECT id, created_at, actor, source, method, route, action, request_details, response_status
               FROM AuditLog
               ORDER BY id ASC'''
        ).fetchall()
    finally:
        legacy_conn.close()

    audit_conn = sqlite3.connect(str(AUDIT_DB))
    try:
        _create_audit_log_schema(audit_conn)
        if legacy_rows:
            audit_conn.executemany(
                '''INSERT OR IGNORE INTO AuditLog (
                    id, created_at, actor, source, method, route, action, request_details, response_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                legacy_rows,
            )
        audit_conn.commit()
    finally:
        audit_conn.close()

    cleanup_conn = sqlite3.connect(str(SETTINGS_DB))
    try:
        cleanup_conn.execute('DROP TABLE IF EXISTS AuditLog')
        cleanup_conn.commit()
    finally:
        cleanup_conn.close()


def ensure_audit_log_table():
    """Create audit log table if missing."""
    conn = sqlite3.connect(str(AUDIT_DB))
    try:
        _create_audit_log_schema(conn)
        conn.commit()
    finally:
        conn.close()
    _migrate_legacy_audit_log()


def purge_old_audit_logs():
    """Delete audit records older than 30 days."""
    ensure_audit_log_table()
    cutoff = (utc_now() - timedelta(days=30)).isoformat(timespec='seconds').replace('+00:00', 'Z')
    conn = sqlite3.connect(str(AUDIT_DB))
    try:
        conn.execute('DELETE FROM AuditLog WHERE created_at < ?', (cutoff,))
        conn.commit()
    finally:
        conn.close()


def write_audit_log(actor, source, method, route, request_details, response_status):
    """Persist an audit entry for dashboard edits."""
    purge_old_audit_logs()
    method_upper = str(method or '').upper()
    action_map = {
        'POST': 'update',
        'PUT': 'update',
        'PATCH': 'update',
        'DELETE': 'delete',
    }
    action = action_map.get(method_upper, method_upper.lower() or 'unknown')
    conn = sqlite3.connect(str(AUDIT_DB))
    try:
        conn.execute(
            '''INSERT INTO AuditLog (
                created_at, actor, source, method, route, action, request_details, response_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                utc_now_iso_z(),
                str(actor or 'Unknown'),
                str(source or 'unknown'),
                method_upper,
                str(route or ''),
                action,
                _json_dump_limited(request_details),
                int(response_status or 0),
            )
        )
        conn.commit()
    finally:
        conn.close()


@app.before_request
def ensure_session_csrf_token():
    """Ensure each session has a CSRF token for mutating API calls."""
    if request.path.startswith('/static/'):
        return None
    get_or_create_csrf_token()


@app.before_request
def require_discord_oauth_login():
    """Protect Online_Web_Server behind Discord OAuth login."""
    if OFFLINE_MODE:
        return None
    if request.method == 'OPTIONS':
        return None

    if request.path == '/favicon.ico':
        return ('', 204)

    if request.path.startswith('/static/'):
        return None

    public_endpoints = {'login', 'oauth_callback', 'logout', 'static'}
    if request.endpoint in public_endpoints:
        return None

    if current_discord_user():
        return None

    next_path = normalize_next_path(request.full_path[:-1] if request.full_path.endswith('?') else request.full_path)
    if request.path.startswith('/api/'):
        return jsonify({
            'error': 'Authentication required',
            'login_url': url_for('login', next=next_path),
        }), 401

    return redirect(url_for('login', next=next_path))


@app.before_request
def enforce_api_csrf():
    """Require CSRF token for all authenticated mutating API requests."""
    if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        return None
    if not request.path.startswith('/api/'):
        return None

    csrf_header = request.headers.get('X-CSRF-Token')
    csrf_body = None
    if not csrf_header:
        body = request.get_json(silent=True) or {}
        csrf_body = body.get('csrf_token') if isinstance(body, dict) else None

    if is_valid_csrf_token(csrf_header or csrf_body):
        return None
    return jsonify({'error': 'Invalid or missing CSRF token.'}), 403


@app.before_request
def capture_audit_request_context():
    """Capture request payload once for audit logging."""
    if request.path.startswith('/api/') and request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        g.audit_payload = request.get_json(silent=True)


_LONG_CACHE_EXTENSIONS = (
    '.css', '.js', '.mjs', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg',
    '.ico', '.woff', '.woff2', '.ttf', '.map', '.avif'
)


def _is_cacheable_asset_request(path):
    lowered = str(path or '').lower()
    if lowered.startswith('/static/'):
        return True
    if lowered.endswith('/icon') or lowered.endswith('/image'):
        return True
    return False


def _apply_browser_cache_headers(response):
    path = str(request.path or '').lower()
    method = str(request.method or '').upper()

    if method not in {'GET', 'HEAD'}:
        return response

    if response.status_code == 200 and _is_cacheable_asset_request(path):
        if path.startswith('/static/') and path.endswith(_LONG_CACHE_EXTENSIONS):
            response.headers['Cache-Control'] = 'public, max-age=86400, stale-while-revalidate=604800'
        else:
            response.headers['Cache-Control'] = 'public, max-age=1800, stale-while-revalidate=86400'
        return response

    # Keep authenticated and data responses fresh.
    mimetype = str(response.mimetype or '').lower()
    if path.startswith('/api/') or mimetype in {'text/html', 'application/json'}:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


@app.after_request
def persist_audit_log(response):
    """Write audit logs for successful mutating API calls."""
    try:
        if not request.path.startswith('/api/'):
            return response


        @app.errorhandler(413)
        def request_entity_too_large(_error):
            """Return a consistent JSON error for oversized API uploads."""
            if request.path.startswith('/api/'):
                return jsonify({'error': f'Upload exceeds {MAX_ITEM_IMAGE_UPLOAD_MB}MB limit'}), 413
            return 'Request entity too large', 413
        if request.path == '/api/audit-logs':
            return response
        if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            return response
        if response.status_code >= 400:
            return response

        source = request.headers.get('X-Audit-Source') or 'admin_webpage'
        if source == 'admin_webpage':
            actor = current_audit_actor() or f'Local ({request.remote_addr or "unknown"})'
        else:
            actor = request.headers.get('X-Audit-Actor') or current_audit_actor() or f'Local ({request.remote_addr or "unknown"})'
        payload = getattr(g, 'audit_payload', None)
        write_audit_log(
            actor=actor,
            source=source,
            method=request.method,
            route=request.path,
            request_details=payload,
            response_status=response.status_code,
        )
    except Exception:
        # Audit failures must not block dashboard operations.
        pass
    return _apply_browser_cache_headers(response)

def get_configured_servers():
    """Get configured servers for role lookups."""
    if not SETTINGS_DB.exists():
        return []

    conn = get_db_connection(SETTINGS_DB)
    c = conn.cursor()
    try:
        c.execute('''CREATE TABLE IF NOT EXISTS Server (
            guild_id INTEGER PRIMARY KEY,
            admin_role_id INTEGER,
            admin_channel_id INTEGER,
            member_role_id INTEGER,
            member_channel_id INTEGER
        )''')
        c.execute('SELECT guild_id, admin_role_id, member_role_id FROM Server')
        return c.fetchall() or []
    finally:
        conn.close()


def _resolve_session_user_role(refresh=False):
    """Resolve the dashboard role for the currently logged-in Discord user."""
    user = current_discord_user()
    user_id = str((user or {}).get('id') or '').strip()
    if not user_id:
        return ROLE_UNASSIGNED

    active_guild_id = get_active_server_id()
    if not active_guild_id:
        return ROLE_UNASSIGNED

    cache = session.get('dashboard_role_cache')
    now_ts = int(utc_now().timestamp())
    if (
        not refresh
        and isinstance(cache, dict)
        and cache.get('user_id') == user_id
        and str(cache.get('guild_id') or '') == str(active_guild_id or '')
        and int(cache.get('expires_at') or 0) > now_ts
    ):
        return str(cache.get('role') or ROLE_UNASSIGNED)

    resolved_role = ROLE_UNASSIGNED
    configured_servers = get_configured_servers()

    # Permissions are server-scoped: only evaluate role bindings for the active guild.
    if active_guild_id:
        configured_servers = [
            server for server in configured_servers
            if str(server.get('guild_id') or '').strip() == str(active_guild_id).strip()
        ]

    for server in configured_servers:
        guild_id = server.get('guild_id')
        if not guild_id:
            continue

        member_data = discord_api_get_json(f'/guilds/{guild_id}/members/{user_id}')
        if not isinstance(member_data, dict):
            continue

        role_for_guild = determine_user_role(member_data.get('roles', []), [server])
        if role_for_guild == ROLE_ADMIN:
            resolved_role = ROLE_ADMIN
            break
        if role_for_guild == ROLE_MEMBER:
            resolved_role = ROLE_MEMBER

    session['dashboard_role_cache'] = {
        'user_id': user_id,
        'guild_id': str(active_guild_id or ''),
        'role': resolved_role,
        'expires_at': now_ts + 300,
    }
    return resolved_role


def current_session_role():
    """Return the resolved role for the logged-in website user."""
    if OFFLINE_MODE:
        return ROLE_ADMIN
    return _resolve_session_user_role()


def current_session_user_id():
    """Return the logged-in Discord user ID from session."""
    if OFFLINE_MODE:
        return str(OFFLINE_ADMIN_USER['id'])
    user = current_discord_user()
    return str((user or {}).get('id') or '').strip()


def role_is_member(role_value=None):
    role = str(role_value or current_session_role())
    return role == ROLE_MEMBER


def role_is_member_or_admin(role_value=None):
    role = str(role_value or current_session_role())
    return role in {ROLE_MEMBER, ROLE_ADMIN}


def role_is_admin(role_value=None):
    role = str(role_value or current_session_role())
    return role == ROLE_ADMIN


def get_allowed_dashboard_tabs(role_value=None):
    role = str(role_value or current_session_role())
    fallback_tabs = ROLE_ALLOWED_TABS.get(ROLE_UNASSIGNED, {'overview'})
    return set(ROLE_ALLOWED_TABS.get(role, fallback_tabs))


def tab_allowed_for_current_user(tab_name):
    return tab_name in get_allowed_dashboard_tabs()


def redirect_to_allowed_dashboard_tab():
    allowed_tabs = get_allowed_dashboard_tabs()
    target_tab = 'users' if 'users' in allowed_tabs else 'overview'
    target_path = {
        'overview': '/overview',
        'server': '/serverconfig',
        'server_shop': '/server-shop',
        'shop': '/shop',
        'jobs': '/jobs',
        'items': '/items',
        'settings': '/settings',
        'users': '/users',
        'audit': '/audit',
    }.get(target_tab, '/users')
    return redirect(target_path)


def member_or_admin_read_only_mode():
    """Members are read-only for inventory/currency edits."""
    return role_is_member()


def can_edit_sheet_for_target(target_user_id):
    """Members can edit own sheets; admins can edit any sheet."""
    role = current_session_role()
    if role == ROLE_ADMIN:
        return True
    if role == ROLE_MEMBER:
        return current_session_user_id() == str(target_user_id)
    return False


def can_delete_sheet_for_target(target_user_id):
    """Members can delete own sheets, admins can delete any sheet."""
    role = current_session_role()
    if role == ROLE_MEMBER:
        return current_session_user_id() == str(target_user_id)
    if role == ROLE_ADMIN:
        return True
    return False


def requires_admin_delete_confirm(target_user_id):
    """Admins must type Confirm when deleting another member's sheet."""
    return role_is_admin() and current_session_user_id() != str(target_user_id)


def can_view_sheet_status(target_user_id, sheet_status):
    """Members can view only approved sheets for other users; admins can view all."""
    if role_is_admin():
        return True
    if current_session_role() != ROLE_MEMBER:
        return True
    if current_session_user_id() == str(target_user_id):
        return True
    return str(sheet_status or '').strip().lower() == 'approved'

def get_default_avatar_url(user_id):
    """Return Discord default avatar URL (new-format accounts use 6 colours)."""
    try:
        uid = int(user_id)
        # New-format users (discriminator == "0"): index = (snowflake >> 22) % 6
        # Legacy users: index = discriminator % 5.
        # We can't know the discriminator here, so always use the new formula which
        # covers the full 0-5 range and is correct for every account created after 2023.
        avatar_index = (uid >> 22) % 6
    except (TypeError, ValueError):
        avatar_index = 0
    return f'https://cdn.discordapp.com/embed/avatars/{avatar_index}.png'

def discord_api_get_json(endpoint):
    """Get JSON from Discord REST API using the bot token when available."""
    token = get_discord_bot_token()
    if not token:
        return None

    base_url = f'https://discord.com/api/v10{endpoint}'
    max_attempts = 3
    for attempt in range(max_attempts):
        request = urllib_request.Request(
            base_url,
            headers={
                'Authorization': f'Bot {token}',
                'User-Agent': 'DiscordBotAdminDashboard/1.0'
            }
        )
        try:
            with urllib_request.urlopen(request, timeout=5) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib_error.HTTPError as exc:
            # Retry once or twice when Discord rate-limits the bot API.
            if exc.code == 429 and attempt < (max_attempts - 1):
                retry_after = 1.0
                try:
                    body = exc.read().decode('utf-8')
                    payload = json.loads(body)
                    retry_after = float(payload.get('retry_after') or retry_after)
                except Exception:
                    retry_after = 1.0
                time.sleep(max(0.25, min(retry_after, 5.0)))
                continue
            return None
        except (urllib_error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt < (max_attempts - 1):
                time.sleep(0.35)
                continue
            return None
    return None


def get_cached_discord_basic_profile(user_id):
    """Return cached Discord /users profile with a safe default fallback."""
    uid = str(user_id or '').strip()
    fallback = {
        'username': f'User {uid}' if uid else 'Unknown User',
        'avatar_url': get_default_avatar_url(uid) if uid else get_default_avatar_url('0'),
        'role': 'Unknown',
    }
    if not uid or not _SNOWFLAKE_RE.fullmatch(uid):
        return fallback

    now_ts = int(utc_now().timestamp())
    cached = _DISCORD_BASIC_PROFILE_MEMORY_CACHE.get(uid)
    if (
        isinstance(cached, dict)
        and int(cached.get('expires_at') or 0) > now_ts
        and isinstance(cached.get('profile'), dict)
    ):
        return dict(cached.get('profile'))

    user_data = discord_api_get_json(f'/users/{uid}')
    profile = dict(fallback)
    if isinstance(user_data, dict):
        profile['username'] = user_data.get('global_name') or user_data.get('username') or profile['username']
        profile['avatar_url'] = build_avatar_url(uid, user_data=user_data)

    _DISCORD_BASIC_PROFILE_MEMORY_CACHE[uid] = {
        'expires_at': now_ts + max(60, int(DISCORD_BASIC_PROFILE_CACHE_TTL_SECONDS or 600)),
        'profile': dict(profile),
    }
    return profile


def get_live_bot_guilds():
    """Return live guild data for the current bot when token access is available."""
    guilds = []
    after = None

    while True:
        endpoint = '/users/@me/guilds?limit=200'
        if after:
            endpoint += f'&after={after}'

        batch = discord_api_get_json(endpoint)
        if not isinstance(batch, list) or not batch:
            break

        guilds.extend(batch)
        if len(batch) < 200:
            break

        last_id = str((batch[-1] or {}).get('id') or '').strip()
        if not _SNOWFLAKE_RE.fullmatch(last_id):
            break
        if last_id == after:
            break
        after = last_id

    return guilds


def get_all_guild_members(configured_servers):
    """Fetch all members from every configured guild via Discord API.

    Returns a dict of  user_id -> {'username', 'avatar_url', 'role'}  covering
    every member currently on the server, regardless of whether they have sheets.
    Bots are excluded automatically.
    """
    members: dict = {}
    for server in configured_servers:
        guild_id = str(server.get('guild_id') or '').strip()
        if not guild_id:
            continue

        after = '0'
        while True:
            batch = discord_api_get_json(
                f'/guilds/{guild_id}/members?limit=1000&after={after}'
            )
            if not isinstance(batch, list) or not batch:
                break

            for member in batch:
                user = member.get('user') or {}
                uid = str(user.get('id') or '').strip()
                if not uid or user.get('bot'):
                    continue
                if uid in members:
                    after = uid
                    continue
                username = (
                    member.get('nick')
                    or user.get('global_name')
                    or user.get('username')
                    or f'User {uid}'
                )
                avatar_url = build_avatar_url(uid, user_data=user, member_data={**member, 'guild_id': guild_id})
                role = determine_user_role(member.get('roles', []), [server])
                members[uid] = {
                    'username': username,
                    'avatar_url': avatar_url,
                    'role': role,
                }
                after = uid

            if len(batch) < 1000:
                break

    return members


def get_live_bot_guild_lookup():
    """Map live guild IDs to guild names for dashboard display."""
    lookup = {}
    for guild in get_live_bot_guilds():
        guild_id = guild.get('id')
        guild_name = guild.get('name')
        if guild_id and guild_name:
            lookup[str(guild_id)] = str(guild_name)
    return lookup


def resolve_guild_name(guild_id, guild_lookup=None):
    """Resolve a guild name from cache, with API fallback by guild ID."""
    guild_id_str = str(guild_id or '').strip()
    if not guild_id_str:
        return None

    if isinstance(guild_lookup, dict):
        cached = guild_lookup.get(guild_id_str)
        if cached:
            return str(cached)

    guild_data = discord_api_get_json(f'/guilds/{guild_id_str}')
    if isinstance(guild_data, dict):
        guild_name = str(guild_data.get('name') or '').strip()
        if guild_name:
            if isinstance(guild_lookup, dict):
                guild_lookup[guild_id_str] = guild_name
            return guild_name

    return None


def build_guild_icon_url(guild_id, icon_hash, size=128):
    """Build CDN icon URL for guild icon hashes."""
    guild_id_str = str(guild_id or '').strip()
    icon_hash_str = str(icon_hash or '').strip()
    if not guild_id_str or not icon_hash_str:
        return None
    ext = 'gif' if icon_hash_str.startswith('a_') else 'png'
    return f'https://cdn.discordapp.com/icons/{guild_id_str}/{icon_hash_str}.{ext}?size={int(size)}'


def get_cached_server_icon_url(icon_file):
    """Return local static URL for cached guild icon file."""
    icon_name = str(icon_file or '').strip()
    if not icon_name:
        return None
    return f'/static/server_icons/{icon_name}'


def get_server_cache_lookup():
    """Load cached guild metadata from Settings.db."""
    ensure_settings_schema()
    conn = get_db_connection(SETTINGS_DB)
    c = conn.cursor()
    try:
        c.execute('SELECT guild_id, guild_name, icon_hash, icon_file, updated_at FROM ServerCache')
        rows = c.fetchall() or []
    finally:
        conn.close()

    lookup = {}
    for row in rows:
        guild_id = str(row.get('guild_id') or '').strip()
        if not guild_id:
            continue
        icon_file = str(row.get('icon_file') or '').strip() or None
        lookup[guild_id] = {
            'guild_name': str(row.get('guild_name') or '').strip() or None,
            'icon_hash': str(row.get('icon_hash') or '').strip() or None,
            'icon_file': icon_file,
            'icon_url': get_cached_server_icon_url(icon_file),
            'updated_at': int(row.get('updated_at') or 0),
        }
    return lookup


def upsert_server_cache_entries(entries):
    """Persist cached guild metadata entries."""
    if not entries:
        return

    ensure_settings_schema()
    conn = sqlite3.connect(str(SETTINGS_DB))
    try:
        conn.executemany(
            '''INSERT INTO ServerCache (guild_id, guild_name, icon_hash, icon_file, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
                   guild_name=excluded.guild_name,
                   icon_hash=excluded.icon_hash,
                   icon_file=excluded.icon_file,
                   updated_at=excluded.updated_at''',
            entries,
        )
        conn.commit()
    finally:
        conn.close()


def cache_server_icon(guild_id, icon_hash):
    """Download and store a guild icon locally for reuse."""
    icon_url = build_guild_icon_url(guild_id, icon_hash, size=128)
    if not icon_url:
        return None

    ext = 'gif' if str(icon_hash).startswith('a_') else 'png'
    file_name = f'{guild_id}_{icon_hash}.{ext}'
    target_path = SERVER_ICON_CACHE_DIR / file_name
    if not target_path.exists():
        request_obj = urllib_request.Request(
            icon_url,
            headers={'User-Agent': 'DiscordBotAdminDashboard/1.0'}
        )
        with urllib_request.urlopen(request_obj, timeout=10) as response:
            target_path.write_bytes(response.read())
    return file_name


def _clear_visible_server_options_cache(user_id=None):
    """Clear in-memory visible server options cache for one user or all users."""
    if user_id is None:
        _VISIBLE_SERVER_OPTIONS_MEMORY_CACHE.clear()
        return
    _VISIBLE_SERVER_OPTIONS_MEMORY_CACHE.pop(str(user_id), None)


def get_dynamic_server_options():
    """Return merged server options from configured rows and live bot guilds."""
    now_ts = int(utc_now().timestamp())
    cached_dynamic = _DYNAMIC_SERVER_OPTIONS_MEMORY_CACHE.get('data')
    if (
        isinstance(cached_dynamic, list)
        and int(_DYNAMIC_SERVER_OPTIONS_MEMORY_CACHE.get('expires_at') or 0) > now_ts
    ):
        return [dict(row) for row in cached_dynamic]

    ensure_settings_schema()
    live_guilds = get_live_bot_guilds()
    cache_lookup = get_server_cache_lookup()
    live_map = {}
    cache_updates = []
    now_ts = int(utc_now().timestamp())
    for guild in live_guilds:
        guild_id = str((guild or {}).get('id') or '').strip()
        if not _SNOWFLAKE_RE.fullmatch(guild_id):
            continue
        icon_hash = str((guild or {}).get('icon') or '').strip() or None
        icon_file = None
        icon_local_url = None
        if icon_hash:
            try:
                icon_file = cache_server_icon(guild_id, icon_hash)
            except Exception:
                icon_file = None
        if icon_file:
            icon_local_url = get_cached_server_icon_url(icon_file)
        live_map[guild_id] = {
            'guild_name': str((guild or {}).get('name') or '').strip() or None,
            'icon_hash': icon_hash,
            'icon_file': icon_file,
            'icon_url': icon_local_url or build_guild_icon_url(guild_id, icon_hash),
        }
        cache_updates.append((guild_id, live_map[guild_id]['guild_name'], icon_hash, icon_file, now_ts))

    if cache_updates:
        upsert_server_cache_entries(cache_updates)

    conn = get_db_connection(SETTINGS_DB)
    c = conn.cursor()
    c.execute('SELECT * FROM Server')
    configured_rows = c.fetchall() or []
    conn.close()

    merged = {}
    for row in configured_rows:
        server = dict(row)
        for key in ('guild_id', 'admin_role_id', 'admin_channel_id', 'member_role_id', 'member_channel_id'):
            if server.get(key) is not None:
                server[key] = str(server[key])

        guild_id = str(server.get('guild_id') or '').strip()
        if not guild_id:
            continue

        live = live_map.get(guild_id) or {}
        cached = cache_lookup.get(guild_id) or {}
        server['guild_name'] = live.get('guild_name') or cached.get('guild_name') or resolve_guild_name(guild_id)
        server['icon_hash'] = live.get('icon_hash') or cached.get('icon_hash')
        server['icon_file'] = live.get('icon_file') or cached.get('icon_file')
        server['icon_url'] = live.get('icon_url') or cached.get('icon_url')
        server['configured'] = True
        server['live'] = guild_id in live_map
        merged[guild_id] = server

    for guild_id, live in live_map.items():
        if guild_id in merged:
            continue
        merged[guild_id] = {
            'guild_id': guild_id,
            'admin_role_id': None,
            'admin_channel_id': None,
            'member_role_id': None,
            'member_channel_id': None,
            'guild_name': live.get('guild_name') or f'Guild {guild_id}',
            'icon_hash': live.get('icon_hash'),
            'icon_file': live.get('icon_file'),
            'icon_url': live.get('icon_url'),
            'configured': False,
            'live': True,
        }

    options = list(merged.values())
    options.sort(key=lambda row: (str(row.get('guild_name') or '').lower(), str(row.get('guild_id') or '')))
    _DYNAMIC_SERVER_OPTIONS_MEMORY_CACHE['data'] = [dict(row) for row in options]
    _DYNAMIC_SERVER_OPTIONS_MEMORY_CACHE['expires_at'] = now_ts + max(10, int(DYNAMIC_SERVER_OPTIONS_CACHE_TTL_SECONDS or 30))
    return options


def get_visible_server_options_for_current_user():
    """Return only servers where the logged-in website user is a member."""
    if OFFLINE_MODE:
        return get_dynamic_server_options()

    user_id = current_session_user_id()
    if not user_id:
        return []

    now_ts = int(utc_now().timestamp())
    cached = _VISIBLE_SERVER_OPTIONS_MEMORY_CACHE.get(str(user_id))
    if (
        isinstance(cached, dict)
        and str(cached.get('user_id') or '') == str(user_id)
        and int(cached.get('expires_at') or 0) > now_ts
        and isinstance(cached.get('servers'), list)
    ):
        return [dict(row) for row in cached.get('servers')]

    visible = []
    for server in get_dynamic_server_options():
        guild_id = str(server.get('guild_id') or '').strip()
        if not guild_id:
            continue
        member_data = discord_api_get_json(f'/guilds/{guild_id}/members/{user_id}')
        if isinstance(member_data, dict):
            visible.append(server)

    _VISIBLE_SERVER_OPTIONS_MEMORY_CACHE[str(user_id)] = {
        'user_id': str(user_id),
        'expires_at': now_ts + max(15, int(VISIBLE_SERVER_OPTIONS_CACHE_TTL_SECONDS or 90)),
        'servers': [dict(row) for row in visible],
    }
    return visible


def get_active_server_id():
    """Return active server from session when valid."""
    stored = str(session.get('active_server_id') or '').strip()
    if not stored:
        return None
    if not _SNOWFLAKE_RE.fullmatch(stored):
        session.pop('active_server_id', None)
        return None
    return stored


def set_active_server_id(guild_id):
    """Set or clear active server id in session."""
    value = str(guild_id or '').strip()
    if not value:
        session.pop('active_server_id', None)
        session.pop('dashboard_role_cache', None)
        _clear_visible_server_options_cache(current_session_user_id())
        return None
    if not _SNOWFLAKE_RE.fullmatch(value):
        raise ValueError('Guild ID must be a valid Discord snowflake')
    session['active_server_id'] = value
    session.pop('dashboard_role_cache', None)
    return value


def get_active_server_context():
    """Return active server and visible options for the current user."""
    options = get_visible_server_options_for_current_user()
    active_server_id = get_active_server_id()
    active_server = next((row for row in options if str(row.get('guild_id')) == str(active_server_id)), None)
    if active_server_id and not active_server:
        session.pop('active_server_id', None)
        active_server_id = None
    return {
        'active_server_id': active_server_id,
        'active_server': active_server,
        'servers': options,
    }


def get_selected_server_id_required():
    """Return the currently selected server id or raise a user-facing error."""
    guild_id = get_active_server_id()
    if not guild_id:
        raise ValueError('Select a server first.')
    return guild_id


def filter_servers_for_guild(configured_servers, guild_id):
    """Return configured server rows limited to one guild."""
    selected = str(guild_id or '').strip()
    return [server for server in (configured_servers or []) if str(server.get('guild_id') or '').strip() == selected]


def sheet_matches_selected_server(user_id, sheet_id, guild_id):
    """Return True when a sheet belongs to the currently selected guild."""
    selected = str(guild_id or '').strip()
    if not selected:
        return False

    if SETTINGS_DB.exists():
        ensure_sheet_index_schema()
        conn = get_db_connection(SETTINGS_DB)
        c = conn.cursor()
        try:
            c.execute(
                'SELECT 1 FROM SheetIndex WHERE user_id=? AND sheet_id=? AND CAST(guild_id AS TEXT)=? LIMIT 1',
                (str(user_id), str(sheet_id), selected),
            )
            if c.fetchone():
                return True
        finally:
            conn.close()

    storage_sheet_id = _resolve_storage_sheet_id(user_id, sheet_id)
    if not storage_sheet_id:
        return False

    conn = sqlite3.connect(str(SHEETS_DB))
    try:
        row = conn.execute(
            '''SELECT 1
               FROM sheets s
               JOIN characters c ON c.character_id=s.character_id
               WHERE c.user_id=? AND s.sheet_id=? AND CAST(c.guild_id AS TEXT)=?
               LIMIT 1''',
            (str(user_id), int(storage_sheet_id), selected),
        ).fetchone()
        return bool(row)
    finally:
        conn.close()


def get_live_bot_guild_count():
    """Return the number of guilds the bot is currently in, when token access is available."""
    guilds = get_live_bot_guilds()
    return len(guilds) if guilds else None

def build_avatar_url(user_id, user_data=None, member_data=None):
    """Build best available avatar URL for a Discord user."""
    if member_data and member_data.get('avatar') and member_data.get('guild_id'):
        return (
            f"https://cdn.discordapp.com/guilds/{member_data['guild_id']}/users/{user_id}/avatars/"
            f"{member_data['avatar']}.png?size=128"
        )

    if user_data and user_data.get('avatar'):
        return f"https://cdn.discordapp.com/avatars/{user_id}/{user_data['avatar']}.png?size=128"

    return get_default_avatar_url(user_id)

def determine_user_role(member_role_ids, configured_servers):
    """Map Discord member roles to configured bot roles."""
    member_role_ids = {str(role_id) for role_id in (member_role_ids or [])}
    for server in configured_servers:
        admin_role_id = server.get('admin_role_id')
        member_role_id = server.get('member_role_id')
        if admin_role_id and str(admin_role_id) in member_role_ids:
            return 'Admin'
        if member_role_id and str(member_role_id) in member_role_ids:
            return 'Member'
    return 'Unassigned'

def get_discord_user_profile(user_id, configured_servers):
    """Fetch username, avatar, and configured role classification from Discord when possible."""
    user_data = discord_api_get_json(f'/users/{user_id}')
    profile = {
        'username': f'User {user_id}',
        'avatar_url': get_default_avatar_url(user_id),
        'role': 'Unknown'
    }

    if user_data:
        profile['username'] = user_data.get('global_name') or user_data.get('username') or profile['username']
        profile['avatar_url'] = build_avatar_url(user_id, user_data=user_data)

    for server in configured_servers:
        guild_id = server.get('guild_id')
        if not guild_id:
            continue

        member_data = discord_api_get_json(f'/guilds/{guild_id}/members/{user_id}')
        if not member_data:
            continue

        member_data['guild_id'] = guild_id
        profile['username'] = (
            member_data.get('nick')
            or (member_data.get('user') or {}).get('global_name')
            or (member_data.get('user') or {}).get('username')
            or profile['username']
        )
        profile['avatar_url'] = build_avatar_url(user_id, user_data=member_data.get('user'), member_data=member_data)
        profile['role'] = determine_user_role(member_data.get('roles', []), configured_servers)
        return profile

    return profile

def get_sheet_status_counts(user_id):
    """Aggregate sheet counts by status for a user from Sheets.db."""
    counts = {
        'approved': 0,
        'denied': 0,
        'drafts': 0,
        'discuss': 0,
        'imported': 0,
    }

    ensure_sheet_storage_schema()
    conn = sqlite3.connect(str(SHEETS_DB))
    try:
        rows = conn.execute(
            '''SELECT s.status
               FROM sheets s
               JOIN characters c ON c.character_id=s.character_id
               WHERE c.user_id=?''',
            (str(user_id),),
        ).fetchall()
        for row in rows:
            status = str((row[0] if row else '') or '').strip().lower()
            if status == 'approved':
                counts['approved'] += 1
            elif status == 'denied':
                counts['denied'] += 1
            elif status == 'draft':
                counts['drafts'] += 1
            elif status == 'discuss':
                counts['discuss'] += 1
            elif status == 'imported':
                counts['imported'] += 1
    finally:
        conn.close()

    return counts

def get_indexed_user_metadata(guild_id=None):
    """Read user metadata from Settings.db (UserProfile) and sheet counts from Sheets.db."""
    metadata = {}
    selected_guild_id = str(guild_id or '').strip()

    # ---- Profile info from UserProfile (Settings.db) ----
    if SETTINGS_DB.exists():
        ensure_sheet_index_schema()
        conn = get_db_connection(SETTINGS_DB)
        c = conn.cursor()
        try:
            c.execute(
                '''CREATE TABLE IF NOT EXISTS UserProfile (
                    user_id TEXT PRIMARY KEY,
                    guild_id INTEGER,
                    username TEXT NOT NULL,
                    avatar_url TEXT,
                    role_label TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                )'''
            )
            if selected_guild_id:
                c.execute(
                    'SELECT user_id, username, avatar_url, role_label FROM UserProfile WHERE CAST(guild_id AS TEXT)=?',
                    (selected_guild_id,),
                )
            else:
                c.execute('SELECT user_id, username, avatar_url, role_label FROM UserProfile')
            for row in c.fetchall():
                metadata[row['user_id']] = {
                    'username': row['username'],
                    'avatar_url': row.get('avatar_url') or get_default_avatar_url(row['user_id']),
                    'role': row.get('role_label') or 'Unknown',
                    'counts': {'approved': 0, 'denied': 0, 'drafts': 0, 'discuss': 0, 'imported': 0, 'imported': 0},
                }
        finally:
            conn.close()

    # ---- Sheet counts from Sheets.db (authoritative source) ----
    if SHEETS_DB.exists():
        ensure_sheet_storage_schema()
        conn = sqlite3.connect(str(SHEETS_DB))
        conn.row_factory = sqlite3.Row
        try:
            if selected_guild_id:
                rows = conn.execute(
                    '''SELECT c.user_id,
                              SUM(CASE WHEN LOWER(s.status)='approved' THEN 1 ELSE 0 END) AS approved,
                              SUM(CASE WHEN LOWER(s.status)='denied'   THEN 1 ELSE 0 END) AS denied,
                              SUM(CASE WHEN LOWER(s.status)='draft'    THEN 1 ELSE 0 END) AS drafts,
                              SUM(CASE WHEN LOWER(s.status)='discuss'  THEN 1 ELSE 0 END) AS discuss,
                              SUM(CASE WHEN LOWER(s.status)='imported' THEN 1 ELSE 0 END) AS imported
                       FROM characters c
                       JOIN sheets s ON s.character_id = c.character_id
                       WHERE CAST(c.guild_id AS TEXT)=?
                       GROUP BY c.user_id''',
                    (selected_guild_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    '''SELECT c.user_id,
                          SUM(CASE WHEN LOWER(s.status)='approved' THEN 1 ELSE 0 END) AS approved,
                          SUM(CASE WHEN LOWER(s.status)='denied'   THEN 1 ELSE 0 END) AS denied,
                          SUM(CASE WHEN LOWER(s.status)='draft'    THEN 1 ELSE 0 END) AS drafts,
                          SUM(CASE WHEN LOWER(s.status)='discuss'  THEN 1 ELSE 0 END) AS discuss,
                          SUM(CASE WHEN LOWER(s.status)='imported' THEN 1 ELSE 0 END) AS imported
                   FROM characters c
                   JOIN sheets s ON s.character_id = c.character_id
                   GROUP BY c.user_id'''
                ).fetchall()
        finally:
            conn.close()

        for row in rows:
            uid = row['user_id']
            entry = metadata.setdefault(
                uid,
                {
                    'username': f'User {uid}',
                    'avatar_url': get_default_avatar_url(uid),
                    'role': 'Unknown',
                    'counts': {'approved': 0, 'denied': 0, 'drafts': 0, 'discuss': 0, 'imported': 0},
                },
            )
            entry['counts'] = {
                'approved': row['approved'] or 0,
                'denied':   row['denied']   or 0,
                'drafts':   row['drafts']   or 0,
                'discuss':  row['discuss']  or 0,
                'imported': row['imported'] or 0,
            }

    return metadata


def _auto_register_unindexed_sheets(user_id: str) -> None:
    """Backfill SheetIndex for any Sheets.db sheets that have no mapping yet.

    The Discord bot creates characters/sheets directly in Sheets.db without
    writing a SheetIndex entry.  This helper discovers those orphaned sheets and
    registers them so the web UI can display and navigate to them.
    """
    if not SHEETS_DB.exists() or not SETTINGS_DB.exists():
        return

    ensure_sheet_storage_schema()
    ensure_sheet_index_schema()

    # Find all (character, sheet) pairs for this user in Sheets.db.
    conn_sheets = sqlite3.connect(str(SHEETS_DB))
    conn_sheets.row_factory = sqlite3.Row
    try:
        raw_sheets = conn_sheets.execute(
            '''SELECT c.character_id, c.user_id, c.guild_id, c.name AS character_name,
                      s.sheet_id AS storage_sheet_id, s.status, s.created_at, s.updated_at
               FROM characters c
               JOIN sheets s ON s.character_id = c.character_id
               WHERE c.user_id = ?''',
            (str(user_id),),
        ).fetchall()
    finally:
        conn_sheets.close()

    if not raw_sheets:
        return

    # Find which storage_sheet_ids already have a SheetIndex entry.
    conn_idx = sqlite3.connect(str(SETTINGS_DB))
    conn_idx.row_factory = sqlite3.Row
    try:
        existing = {
            row['storage_sheet_id']
            for row in conn_idx.execute(
                'SELECT storage_sheet_id FROM SheetIndex WHERE user_id=? AND storage_sheet_id IS NOT NULL',
                (str(user_id),),
            ).fetchall()
            if row['storage_sheet_id']
        }

        for row in raw_sheets:
            sid = row['storage_sheet_id']
            if sid in existing:
                continue
            # Generate a stable 6-char hex external ID from the integer sheet_id.
            ext_id = f'{sid:06X}'
            conn_idx.execute(
                '''INSERT OR IGNORE INTO SheetIndex
                       (user_id, guild_id, sheet_id, sheet_name, status,
                        created_at, updated_at, storage_sheet_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    str(user_id),
                    row['guild_id'],
                    ext_id,
                    row['character_name'] or ext_id,
                    row['status'] or 'Draft',
                    row['created_at'] or 0,
                    row['updated_at'] or 0,
                    sid,
                ),
            )
        conn_idx.commit()
    finally:
        conn_idx.close()


# ===== ROUTES =====

@app.route('/login')
def login():
    """Show the Discord OAuth login page."""
    if OFFLINE_MODE:
        return redirect('/overview')
    next_path = normalize_next_path(request.args.get('next'))
    if current_discord_user():
        return redirect(next_path)

    oauth_error = str(request.args.get('error_message') or '').strip()
    oauth_configured = is_discord_oauth_configured()
    discord_login_url = None

    if oauth_configured:
        state_value = secrets.token_urlsafe(24)
        state_map = session.get('discord_oauth_state_map')
        if not isinstance(state_map, dict):
            state_map = {}

        # Keep a small rolling window of valid states for parallel requests/tabs.
        state_map[state_value] = next_path
        while len(state_map) > 20:
            oldest_key = next(iter(state_map))
            state_map.pop(oldest_key, None)

        session['discord_oauth_state_map'] = state_map
        discord_login_url = build_discord_login_url(state_value)
    elif not oauth_error:
        oauth_error = 'Discord OAuth is not configured yet. Fill in Online_Web_Server/.env before using this site.'

    return render_template(
        'login.html',
        oauth_configured=oauth_configured,
        oauth_error=oauth_error,
        discord_login_url=discord_login_url,
    )


@app.route('/callback')
def oauth_callback():
    """Finish Discord OAuth and create the local session."""
    if OFFLINE_MODE:
        return redirect('/overview')
    next_path = normalize_next_path(session.pop('discord_oauth_next', None))
    if not is_discord_oauth_configured():
        return redirect(url_for('login', error_message='Discord OAuth is not configured yet.'))

    discord_error = str(request.args.get('error') or '').strip()
    if discord_error:
        description = str(request.args.get('error_description') or discord_error).strip()
        return redirect(url_for('login', error_message=description, next=next_path))

    received_state = str(request.args.get('state') or '').strip()
    state_map = session.get('discord_oauth_state_map')
    if not isinstance(state_map, dict):
        state_map = {}

    mapped_next_path = state_map.pop(received_state, None) if received_state else None
    session['discord_oauth_state_map'] = state_map

    if not mapped_next_path:
        return redirect(url_for('login', error_message='Discord login verification failed. Please try again.', next=next_path))

    next_path = normalize_next_path(mapped_next_path)

    code_value = str(request.args.get('code') or '').strip()
    if not code_value:
        return redirect(url_for('login', error_message='Discord did not return an authorization code.', next=next_path))

    try:
        token_payload = exchange_discord_code(code_value)
        access_token = str(token_payload.get('access_token') or '').strip()
        if not access_token:
            raise ValueError('Discord did not return an access token.')

        user_payload = fetch_discord_oauth_user(access_token)
        session['discord_user'] = format_session_user(user_payload)
        session.permanent = True
    except urllib_error.HTTPError as exc:
        # Surface Discord's JSON error payload (e.g. invalid_client, invalid_grant)
        # instead of only "HTTP Error 403" so configuration issues are obvious.
        details = str(exc)
        try:
            raw_body = exc.read().decode('utf-8', errors='replace')
            parsed = json.loads(raw_body)
            details = str(parsed.get('error_description') or parsed.get('error') or raw_body)
        except Exception:
            pass
        return redirect(url_for('login', error_message=f'Discord login failed: {details}', next=next_path))
    except (urllib_error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return redirect(url_for('login', error_message=f'Discord login failed: {exc}', next=next_path))

    return redirect(next_path)


@app.route('/logout')
def logout():
    """End the local session."""
    if OFFLINE_MODE:
        _clear_visible_server_options_cache(current_session_user_id() or 'offline')
        return redirect('/overview')
    logout_user_id = str((session.get('discord_user') or {}).get('id') or '').strip() or current_session_user_id()
    session.pop('discord_user', None)
    session.pop('discord_oauth_state', None)
    session.pop('discord_oauth_next', None)
    session.pop('discord_oauth_state_map', None)
    session.pop('dashboard_role_cache', None)
    _clear_visible_server_options_cache(logout_user_id)
    return redirect(url_for('login'))

@app.route('/')
def index():
    """Selector homepage for choosing the active server."""
    context = get_active_server_context()
    return render_template(
        'server_selector.html',
        active_server_id=context['active_server_id'],
        active_server=context['active_server'],
        server_options=context['servers'],
    )


@app.route('/dashboard')
def dashboard_home():
    """Dashboard entrypoint after selecting an active server."""
    if current_session_role() == ROLE_UNASSIGNED:
        return render_no_role_access()
    return redirect('/overview')


def render_no_role_access():
    """Render access denied page for users without configured guild roles."""
    active_context = get_active_server_context()
    return render_template(
        'no_role_access.html',
        active_server_id=active_context['active_server_id'],
        active_server_name=(active_context['active_server'] or {}).get('guild_name') if active_context['active_server'] else '',
    ), 403

def render_dashboard(tab_name, initial_user_id=None, initial_sheet_id=None):
    """Render dashboard template with selected tab."""
    selected_tab = tab_name if tab_name in DASHBOARD_TABS else 'overview'
    role = current_session_role()
    if role == ROLE_UNASSIGNED:
        return render_no_role_access()
    allowed_tabs = get_allowed_dashboard_tabs(role)
    if selected_tab not in allowed_tabs:
        selected_tab = 'users' if 'users' in allowed_tabs else 'overview'

    permissions = {
        'can_edit_inventory': role_is_admin(role),
        'can_edit_own_sheets': role_is_member_or_admin(role),
        'can_delete_other_sheets': role_is_admin(role),
        'can_manage_server_fields': role_is_admin(role),
        'can_edit_server_ids': role_is_admin(role),
        'can_change_sheet_status': role_is_admin(role),
    }

    active_context = get_active_server_context()

    return render_template(
        'admin_dashboard.html',
        active_tab=selected_tab,
        initial_user_id=initial_user_id,
        initial_sheet_id=initial_sheet_id,
        session_role=role,
        allowed_tabs=allowed_tabs,
        dashboard_permissions=permissions,
        active_server_id=active_context['active_server_id'],
        active_server_name=(active_context['active_server'] or {}).get('guild_name') if active_context['active_server'] else '',
        active_server_icon_url=(active_context['active_server'] or {}).get('icon_url') if active_context['active_server'] else None,
    )

@app.route('/overview')
def dashboard_overview():
    if not tab_allowed_for_current_user('overview'):
        return redirect_to_allowed_dashboard_tab()
    return render_dashboard('overview')

@app.route('/serverconfig')
def dashboard_serverconfig():
    if not tab_allowed_for_current_user('server'):
        return redirect_to_allowed_dashboard_tab()
    return render_dashboard('server')

@app.route('/shop')
def dashboard_shop():
    if not tab_allowed_for_current_user('shop'):
        return redirect_to_allowed_dashboard_tab()
    return render_dashboard('shop')

@app.route('/server-shop')
def dashboard_server_shop():
    if not tab_allowed_for_current_user('server_shop'):
        return redirect_to_allowed_dashboard_tab()
    return render_dashboard('server_shop')

@app.route('/jobs')
def dashboard_jobs():
    if not tab_allowed_for_current_user('jobs'):
        return redirect_to_allowed_dashboard_tab()
    return render_dashboard('jobs')

@app.route('/items')
def dashboard_items():
    if not tab_allowed_for_current_user('items'):
        return redirect_to_allowed_dashboard_tab()
    return render_dashboard('items')

@app.route('/settings')
def dashboard_settings():
    if not tab_allowed_for_current_user('settings'):
        return redirect_to_allowed_dashboard_tab()
    return render_dashboard('settings')

@app.route('/users')
def dashboard_users():
    if not tab_allowed_for_current_user('users'):
        return redirect_to_allowed_dashboard_tab()
    return render_dashboard('users')


@app.route('/audit')
def dashboard_audit():
    if not tab_allowed_for_current_user('audit'):
        return redirect_to_allowed_dashboard_tab()
    return render_dashboard('audit')


@app.route('/users/<user_id>')
def dashboard_user_detail(user_id):
    if not _USER_ID_RE.fullmatch(user_id):
        abort(404)
    return render_dashboard('users', initial_user_id=user_id)


@app.route('/users/<user_id>/characters/<sheet_id>')
def dashboard_character_detail(user_id, sheet_id):
    if not _USER_ID_RE.fullmatch(user_id):
        abort(404)
    if not _SHEET_ID_RE.fullmatch(sheet_id):
        abort(404)
    return render_dashboard('users', initial_user_id=user_id, initial_sheet_id=sheet_id)

@app.route('/html/<page_name>')
@app.route('/html/<page_name>.html')
def html_page(page_name):
    """Render a template page by name, e.g. /html/admin_dashboard"""
    if not re.fullmatch(r'[A-Za-z0-9_-]+', page_name or ''):
        abort(404)

    template_name = f'{page_name}.html'
    template_path = TEMPLATES_DIR / template_name
    if not template_path.is_file():
        abort(404)

    return render_template(template_name)


@app.route('/api/session-role', methods=['GET'])
def get_session_role():
    """Return current dashboard role/permissions for live role-change checks."""
    refresh = str(request.args.get('refresh', '')).strip().lower() in {'1', 'true', 'yes', 'on'}
    role = _resolve_session_user_role(refresh=refresh)
    return jsonify(
        {
            'role': role,
            'allowed_tabs': sorted(get_allowed_dashboard_tabs(role)),
        }
    )

# --- Server Configuration ---
@app.route('/api/servers', methods=['GET'])
def get_servers():
    """Get all configured servers"""
    if not role_is_admin():
        return jsonify({"error": "Admin role required for server configuration."}), 403
    try:
        ensure_settings_schema()
        guild_lookup = get_live_bot_guild_lookup()
        conn = get_db_connection(SETTINGS_DB)
        c = conn.cursor()
        c.execute('SELECT * FROM Server')
        servers = c.fetchall()
        conn.close()
        return jsonify([_serialize_server_row(server, guild_lookup) for server in (servers or [])])
    except Exception as e:
        return api_error_response('Request failed.', 400, e)


@app.route('/api/server-options', methods=['GET'])
def get_server_options():
    """Return selector server options limited to current user's memberships."""
    try:
        return jsonify(get_visible_server_options_for_current_user())
    except Exception as e:
        return api_error_response('Request failed.', 400, e)


@app.route('/api/active-server', methods=['GET'])
def get_active_server():
    """Return current active server selection."""
    try:
        context = get_active_server_context()
        return jsonify({
            'guild_id': context['active_server_id'],
            'server': context['active_server'],
            'available_count': len(context['servers']),
        })
    except Exception as e:
        return api_error_response('Request failed.', 400, e)


@app.route('/api/active-server', methods=['POST'])
def set_active_server():
    """Set or clear active server selection for this session."""
    try:
        data = request.json or {}
        guild_id = str(data.get('guild_id') or '').strip()
        if not guild_id:
            set_active_server_id(None)
            return jsonify({'status': 'cleared', 'guild_id': None, 'server': None})

        options = get_visible_server_options_for_current_user()
        selected = next((server for server in options if str(server.get('guild_id')) == guild_id), None)
        if not selected:
            _clear_visible_server_options_cache(current_session_user_id())
            options = get_visible_server_options_for_current_user()
            selected = next((server for server in options if str(server.get('guild_id')) == guild_id), None)
        if not selected:
            return jsonify({'error': 'Selected server is not available for this user.'}), 404

        set_active_server_id(guild_id)
        return jsonify({'status': 'success', 'guild_id': guild_id, 'server': selected})
    except ValueError as e:
        return api_error_response('Invalid request data.', 400, e)
    except Exception as e:
        return api_error_response('Request failed.', 400, e)


@app.route('/api/servers', methods=['DELETE'])
def reset_servers():
    """Delete all saved server configuration rows and sheet field definitions."""
    if not role_is_admin():
        return jsonify({"error": "Admin role required for server configuration changes."}), 403
    try:
        conn = get_db_connection(SETTINGS_DB)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS Server (
            guild_id INTEGER PRIMARY KEY,
            admin_role_id INTEGER,
            admin_channel_id INTEGER,
            member_role_id INTEGER,
            member_channel_id INTEGER
        )''')
        c.execute('DELETE FROM Server')
        conn.commit()
        conn.close()
        clear_guild_template_fields()
        return jsonify({"status": "success"})
    except Exception as e:
        return api_error_response('Request failed.', 400, e)


@app.route('/api/servers/<guild_id>', methods=['DELETE'])
def delete_server(guild_id):
    """Delete a saved server configuration row and its sheet field definitions."""
    if not role_is_admin():
        return jsonify({"error": "Admin role required for server configuration changes."}), 403
    try:
        ensure_settings_schema()
        guild_id = parse_snowflake(guild_id, 'Guild ID')
        conn = get_db_connection(SETTINGS_DB)
        c = conn.cursor()
        c.execute('DELETE FROM Server WHERE guild_id=?', (guild_id,))
        conn.commit()
        conn.close()
        clear_guild_template_fields(guild_id)
        return jsonify({"status": "success"})
    except ValueError as e:
        return api_error_response('Invalid request data.', 400, e)
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

# --- Users Overview ---
@app.route('/api/users', methods=['GET'])
def get_users():
    """Return all server members, merged with sheet counts from Sheets.db."""
    try:
        if not role_is_member_or_admin():
            return jsonify({"error": "Members or admins only."}), 403

        selected_guild_id = get_selected_server_id_required()
        session_user_id = current_session_user_id() or 'anonymous'
        role_name = current_session_role()
        cache_key = f"{selected_guild_id}:{session_user_id}:{role_name}"
        now_ts = int(utc_now().timestamp())
        cached = _USERS_LIST_MEMORY_CACHE.get(cache_key)
        if (
            isinstance(cached, dict)
            and int(cached.get('expires_at') or 0) > now_ts
            and isinstance(cached.get('data'), list)
        ):
            return jsonify(cached.get('data'))

        configured_servers = filter_servers_for_guild(get_configured_servers(), selected_guild_id)

        # --- 1. Fetch every current guild member from Discord API ---
        live_members = get_all_guild_members(configured_servers)

        # --- 2. Sheet counts keyed by user_id from Sheets.db ---
        indexed_metadata = get_indexed_user_metadata(selected_guild_id)

        # --- 3. Merge: start from live members, add anyone only in Sheets.db ---
        all_user_ids = set(live_members.keys()) | set(indexed_metadata.keys())

        empty_counts = lambda: {'approved': 0, 'denied': 0, 'drafts': 0, 'discuss': 0}

        users = []
        for user_id in all_user_ids:
            live = live_members.get(user_id)
            indexed = indexed_metadata.get(user_id)
            default_avatar_url = get_default_avatar_url(user_id)

            # Profile: prefer live Discord data; fall back to stored/stub.
            if live:
                profile = live
            elif indexed:
                profile = {
                    'username': indexed['username'],
                    'avatar_url': indexed['avatar_url'],
                    'role': indexed['role'],
                }
                if (
                    profile['username'] == f'User {user_id}'
                    or not str(profile.get('avatar_url') or '').strip()
                    or str(profile.get('avatar_url') or '').strip() == default_avatar_url
                ):
                    basic = get_cached_discord_basic_profile(user_id)
                    profile['username'] = basic.get('username') or profile['username']
                    profile['avatar_url'] = basic.get('avatar_url') or profile['avatar_url']
            else:
                profile = get_cached_discord_basic_profile(user_id)

            counts = indexed['counts'] if indexed else empty_counts()

            users.append({
                'user_id': user_id,
                'username': profile['username'],
                'role': profile['role'],
                'avatar_url': profile['avatar_url'],
                'counts': counts,
                'total_sheets': sum(counts.values()),
                'on_server': user_id in live_members,
            })

        users.sort(key=lambda u: u['username'].lower())
        _USERS_LIST_MEMORY_CACHE[cache_key] = {
            'expires_at': now_ts + max(3, int(USERS_LIST_CACHE_TTL_SECONDS or 8)),
            'data': users,
        }
        return jsonify(users)
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

_USER_ID_RE = re.compile(r'^\d{15,20}$')
_SHEET_ID_RE = re.compile(r'^[A-Za-z0-9]{6,8}$')
_SNOWFLAKE_RE = re.compile(r'^\d{15,20}$')
_VALID_STATUSES = {'Approved', 'Denied', 'Draft', 'Discuss', 'Imported'}


def ensure_currency_table(conn, table_name):
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS currency (
            user_id TEXT NOT NULL,
            guild_id TEXT NOT NULL DEFAULT "",
            character TEXT NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, guild_id, character)
        )'''
    )
    _migrate_currency_guild_id(conn)


def _migrate_currency_guild_id(conn):
    """Migrate legacy currency table to guild-scoped rows."""
    cols = {row[1] for row in conn.execute('PRAGMA table_info(currency)').fetchall()}
    if not cols:
        return
    if 'guild_id' in cols:
        return

    legacy_rows = conn.execute(
        'SELECT user_id, character, amount FROM currency'
    ).fetchall() or []

    conn.execute('ALTER TABLE currency RENAME TO currency_legacy')
    conn.execute(
        '''CREATE TABLE currency (
            user_id TEXT NOT NULL,
            guild_id TEXT NOT NULL DEFAULT "",
            character TEXT NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, guild_id, character)
        )'''
    )
    for user_id, character, amount in legacy_rows:
        conn.execute(
            'INSERT OR REPLACE INTO currency (user_id, guild_id, character, amount) VALUES (?, ?, ?, ?)',
            (str(user_id), '', str(character), float(amount or 0.0)),
        )
    conn.execute('DROP TABLE currency_legacy')
    conn.commit()


def _resolve_character_key(user_id, scope_name, account_default, guild_id=''):
    """Map UI scope to bot character key; sheet IDs resolve via SheetIndex.sheet_name."""
    scope = str(scope_name or '').strip()
    if not scope or scope == account_default:
        return account_default

    if _SHEET_ID_RE.fullmatch(scope) and SETTINGS_DB.exists():
        try:
            conn = get_db_connection(SETTINGS_DB)
            c = conn.cursor()
            if str(guild_id or '').strip():
                c.execute(
                    'SELECT sheet_name FROM SheetIndex WHERE user_id=? AND sheet_id=? AND CAST(guild_id AS TEXT)=? LIMIT 1',
                    (str(user_id), scope, str(guild_id)),
                )
            else:
                c.execute(
                    'SELECT sheet_name FROM SheetIndex WHERE user_id=? AND sheet_id=? LIMIT 1',
                    (str(user_id), scope),
                )
            row = c.fetchone()
            conn.close()
            resolved = str((row or {}).get('sheet_name') or '').strip()
            if resolved:
                return resolved
        except Exception:
            pass

    return scope


def fetch_currency_amount(user_id, table_name='Currency', guild_id=''):
    character_key = _resolve_character_key(user_id, table_name, 'Currency', guild_id=guild_id)
    conn = sqlite3.connect(str(ECONOMY_DB))
    try:
        ensure_currency_table(conn, table_name)
        row = conn.execute(
            'SELECT amount FROM currency WHERE user_id=? AND guild_id=? AND character=?',
            (str(user_id), str(guild_id), character_key),
        ).fetchone()
        return float((row[0] if row else 0.0) or 0.0)
    finally:
        conn.close()


def set_currency_amount(user_id, amount, table_name='Currency', guild_id=''):
    character_key = _resolve_character_key(user_id, table_name, 'Currency', guild_id=guild_id)
    os.makedirs(os.path.dirname(ECONOMY_DB), exist_ok=True)
    conn = sqlite3.connect(str(ECONOMY_DB))
    try:
        ensure_currency_table(conn, table_name)
        conn.execute(
            '''INSERT INTO currency (user_id, guild_id, character, amount) VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, guild_id, character) DO UPDATE SET amount=excluded.amount''',
            (str(user_id), str(guild_id), character_key, float(amount)),
        )
        conn.commit()
    finally:
        conn.close()


def _migrate_inventory_guild_id(conn):
    """Add guild_id column + unique index to inventory table if missing."""
    cols = {row[1] for row in conn.execute('PRAGMA table_info(inventory)').fetchall()}
    if 'guild_id' not in cols:
        conn.execute('ALTER TABLE inventory ADD COLUMN guild_id TEXT NOT NULL DEFAULT ""')
        conn.commit()
    indexes = {row[1] for row in conn.execute('PRAGMA index_list(inventory)').fetchall()}
    if 'inventory_guild_scope_uidx' not in indexes:
        conn.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS inventory_guild_scope_uidx '
            'ON inventory (user_id, guild_id, character, item_name)'
        )
        conn.commit()


def ensure_inventory_table(conn, table_name):
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS inventory (
            user_id TEXT NOT NULL,
            guild_id TEXT NOT NULL DEFAULT "",
            character TEXT NOT NULL,
            item_name TEXT NOT NULL,
            quantity INTEGER,
            description TEXT,
            icon TEXT,
            PRIMARY KEY (user_id, guild_id, character, item_name)
        )'''
    )
    _migrate_inventory_guild_id(conn)


def fetch_inventory_items(user_id, table_name='Inventory', guild_id=''):
    character_key = _resolve_character_key(user_id, table_name, 'Inventory')
    conn = sqlite3.connect(str(INVENTORY_DB))
    try:
        ensure_inventory_table(conn, table_name)
        rows = conn.execute(
            'SELECT item_name, quantity FROM inventory WHERE user_id=? AND guild_id=? AND character=? ORDER BY item_name COLLATE NOCASE',
            (str(user_id), str(guild_id), character_key),
        ).fetchall()
        return [{"item_name": row[0], "quantity": int(row[1] or 0)} for row in rows]
    finally:
        conn.close()


def upsert_inventory_item(user_id, item_name, quantity, table_name='Inventory', guild_id=''):
    character_key = _resolve_character_key(user_id, table_name, 'Inventory')
    os.makedirs(os.path.dirname(INVENTORY_DB), exist_ok=True)
    conn = sqlite3.connect(str(INVENTORY_DB))
    try:
        ensure_inventory_table(conn, table_name)
        existing = conn.execute(
            'SELECT quantity FROM inventory WHERE user_id=? AND guild_id=? AND character=? AND item_name=?',
            (str(user_id), str(guild_id), character_key, item_name),
        ).fetchone()
        if existing:
            conn.execute(
                'UPDATE inventory SET quantity=? WHERE user_id=? AND guild_id=? AND character=? AND item_name=?',
                (int(quantity), str(user_id), str(guild_id), character_key, item_name),
            )
        else:
            conn.execute(
                'INSERT INTO inventory (user_id, guild_id, character, item_name, quantity, description, icon) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (str(user_id), str(guild_id), character_key, item_name, int(quantity), '', ''),
            )
        conn.commit()
    finally:
        conn.close()


def delete_inventory_item(user_id, item_name, table_name='Inventory', guild_id=''):
    character_key = _resolve_character_key(user_id, table_name, 'Inventory')
    conn = sqlite3.connect(str(INVENTORY_DB))
    try:
        ensure_inventory_table(conn, table_name)
        conn.execute(
            'DELETE FROM inventory WHERE user_id=? AND guild_id=? AND character=? AND item_name=?',
            (str(user_id), str(guild_id), character_key, item_name),
        )
        conn.commit()
    finally:
        conn.close()


def fetch_sheet_rows(user_id, sheet_id):
    storage_sheet_id = _resolve_storage_sheet_id(user_id, sheet_id)
    if storage_sheet_id is None:
        raise sqlite3.OperationalError('Sheet not found')

    conn = sqlite3.connect(str(SHEETS_DB))
    conn.row_factory = sqlite3.Row
    try:
        meta = conn.execute(
            '''SELECT c.name AS character_name, s.status AS sheet_status
               FROM sheets s
               JOIN characters c ON c.character_id=s.character_id
               WHERE s.sheet_id=? AND c.user_id=?
               LIMIT 1''',
            (int(storage_sheet_id), str(user_id)),
        ).fetchone()
        if not meta:
            raise sqlite3.OperationalError('Sheet not found')

        rows = [
            ('Name', str(meta['character_name'] or '')),
            ('Status', str(meta['sheet_status'] or 'Draft')),
        ]

        field_rows = conn.execute(
            '''SELECT field_name, value
               FROM sheet_fields
               WHERE sheet_id=?
               ORDER BY sort_order ASC, field_name COLLATE NOCASE ASC''',
            (int(storage_sheet_id),),
        ).fetchall()
        for field in field_rows:
            fname = str(field['field_name'] or '')
            if fname.lower() in {'name', 'status'}:
                continue
            rows.append((fname, '' if field['value'] is None else str(field['value'])))
        return rows
    finally:
        conn.close()


def sheet_icon_exists(user_id, sheet_id):
    try:
        rows = fetch_sheet_rows(user_id, sheet_id)
        icon_row = next((value for field, value in rows if str(field).lower() == 'icon'), '')
        icon_name = str(icon_row or '').strip()
        if not icon_name:
            return False
        return (USERS_DIR / 'images' / str(user_id) / icon_name).exists()
    except Exception:
        return False


def get_configured_sheet_fields():
    """Return distinct admin-configured sheet fields across servers."""
    return list_all_template_field_names()


def build_sheet_detail_payload(user_id, sheet_id, fallback_name=None, fallback_status=None, guild_id=''):
    rows = fetch_sheet_rows(user_id, sheet_id)
    field_map = {str(field_name): data for field_name, data in rows}
    fields = [
        {
            'field_name': str(field_name),
            'data': '' if data is None else str(data),
        }
        for field_name, data in rows
        if str(field_name).lower() != 'icon'
    ]

    # Show admin-defined fields on every sheet, even when unset.
    existing_field_keys = {str(field.get('field_name', '')).strip().lower() for field in fields}
    for configured_field in get_configured_sheet_fields():
        key = configured_field.lower()
        if key in {'icon'}:
            continue
        if key not in existing_field_keys:
            fields.append({'field_name': configured_field, 'data': ''})
            existing_field_keys.add(key)

    return {
        'sheet_id': sheet_id,
        'sheet_name': field_map.get('Name') or fallback_name or sheet_id,
        'status': field_map.get('Status') or fallback_status or 'Draft',
        'currency': fetch_currency_amount(user_id, sheet_id, guild_id=guild_id),
        'inventory': fetch_inventory_items(user_id, sheet_id, guild_id=guild_id),
        'fields': fields,
        'has_icon': sheet_icon_exists(user_id, sheet_id),
    }


def validate_item_name(item_name):
    normalized = str(item_name or '').strip()
    if not normalized:
        raise ValueError('Item name is required')
    return normalized[:200]


def validate_admin_name(value, label='Value', max_len=120):
    """Validate mutable admin-provided names used in routes/UI payloads."""
    normalized = str(value or '').strip()
    if not normalized:
        raise ValueError(f'{label} is required')
    if len(normalized) > max_len:
        raise ValueError(f'{label} must be at most {max_len} characters')
    if any((ord(ch) < 32 or ord(ch) == 127) for ch in normalized):
        raise ValueError(f'{label} contains invalid control characters')
    return normalized


def validate_item_quantity(quantity):
    try:
        parsed = int(quantity)
    except (TypeError, ValueError):
        raise ValueError('Quantity must be a whole number')
    if parsed < 0:
        raise ValueError('Quantity cannot be negative')
    return parsed


def parse_currency_amount(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError('Currency amount must be numeric')


def detect_image_type_from_header(head_bytes):
    """Detect a supported image type from file signature bytes."""
    if not head_bytes:
        return None

    head = bytes(head_bytes)
    if head.startswith(b'\xFF\xD8\xFF'):
        return 'jpeg'
    if head.startswith(b'\x89PNG\r\n\x1A\n'):
        return 'png'
    if head.startswith((b'GIF87a', b'GIF89a')):
        return 'gif'
    if len(head) >= 12 and head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'webp'
    return None


def validate_item_image_upload(file_storage):
    """Validate image upload by size, MIME type, extension, and content signature."""
    filename = str(getattr(file_storage, 'filename', '') or '').strip()
    if not filename:
        raise ValueError('No file selected')

    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ALLOWED_ITEM_IMAGE_EXTENSIONS:
        raise ValueError('File extension must be jpg, jpeg, png, gif, or webp')

    mime_type = str(getattr(file_storage, 'content_type', '') or '').lower().strip()
    if mime_type not in ALLOWED_ITEM_IMAGE_MIME_TYPES:
        raise ValueError('File must be JPEG, PNG, GIF, or WEBP')

    declared_size = request.content_length or 0
    if declared_size > MAX_ITEM_IMAGE_UPLOAD_BYTES:
        raise ValueError(f'Image exceeds {MAX_ITEM_IMAGE_UPLOAD_MB}MB upload limit')

    stream = getattr(file_storage, 'stream', None)
    if stream is None:
        raise ValueError('Invalid upload stream')

    head = stream.read(512)
    stream.seek(0)
    detected = detect_image_type_from_header(head)
    if detected not in ALLOWED_ITEM_IMAGE_SIGNATURES:
        raise ValueError('Uploaded file is not a valid image')

    if ext in {'jpg', 'jpeg'} and detected != 'jpeg':
        raise ValueError('File extension does not match JPEG image content')
    if ext != 'jpg' and ext != 'jpeg' and ext != detected:
        raise ValueError('File extension does not match image content')

    return 'jpg' if detected == 'jpeg' else detected


def parse_snowflake(value, field_name='ID', required=True):
    value = '' if value is None else str(value).strip()
    if not value:
        if required:
            raise ValueError(f'{field_name} is required')
        return None
    if not _SNOWFLAKE_RE.fullmatch(value):
        raise ValueError(f'{field_name} must be a valid Discord snowflake')
    return int(value)


def _serialize_server_row(row, guild_lookup=None):
    if not row:
        return row
    server = dict(row)
    for key in ('guild_id', 'admin_role_id', 'admin_channel_id', 'member_role_id', 'member_channel_id'):
        if server.get(key) is not None:
            server[key] = str(server[key])
    server['guild_name'] = resolve_guild_name(server.get('guild_id'), guild_lookup)
    return server


@app.route('/api/users/<user_id>/detail', methods=['GET'])
def get_user_detail(user_id):
    """Get a user's currency, inventory, and character sheets."""
    if not _USER_ID_RE.fullmatch(user_id):
        return jsonify({"error": "Invalid user ID"}), 400
    try:
        selected_guild_id = get_selected_server_id_required()
        currency = fetch_currency_amount(user_id, 'Currency', guild_id=selected_guild_id)
        inventory = fetch_inventory_items(user_id, 'Inventory', guild_id=selected_guild_id)

        # Ensure any bot-created sheets (no SheetIndex entry) get registered first.
        _auto_register_unindexed_sheets(user_id)

        # Character sheets from SheetIndex
        sheets = []
        if SETTINGS_DB.exists():
            ensure_sheet_index_schema()
            conn = get_db_connection(SETTINGS_DB)
            c = conn.cursor()
            try:
                c.execute(
                    'SELECT sheet_id, sheet_name, status FROM SheetIndex WHERE user_id=? AND CAST(guild_id AS TEXT)=? ORDER BY sheet_name COLLATE NOCASE',
                    (user_id, selected_guild_id)
                )
                index_rows = c.fetchall()
            except Exception:
                index_rows = []
            finally:
                conn.close()

            for row in index_rows:
                sheet_id = row['sheet_id']
                if not _SHEET_ID_RE.fullmatch(sheet_id):
                    continue
                if not can_view_sheet_status(user_id, row['status']):
                    continue
                has_icon = sheet_icon_exists(user_id, sheet_id)
                sheets.append({
                    "sheet_id": sheet_id,
                    "sheet_name": row['sheet_name'],
                    "status": row['status'],
                    "has_icon": has_icon,
                })

        return jsonify({"currency": currency, "inventory": inventory, "sheets": sheets})
    except Exception as e:
        return api_error_response('Internal server error.', 500, e)


@app.route('/api/users/<user_id>/resources', methods=['POST'])
def update_user_resources(user_id):
    """Update global user currency and inventory."""
    if role_is_member():
        return jsonify({"error": "Members can view inventory but cannot edit it."}), 403
    if not _USER_ID_RE.fullmatch(user_id):
        return jsonify({"error": "Invalid user ID"}), 400

    data = request.json or {}
    try:
        selected_guild_id = get_selected_server_id_required()

        if 'currency' in data:
            set_currency_amount(user_id, parse_currency_amount(data.get('currency')), 'Currency', guild_id=selected_guild_id)

        if 'inventory' in data:
            inventory = data.get('inventory') or []
            if not isinstance(inventory, list):
                raise ValueError('Inventory must be a list')

            # Replace full account-scope inventory with submitted values.
            for row in fetch_inventory_items(user_id, 'Inventory', guild_id=selected_guild_id):
                delete_inventory_item(user_id, str(row.get('item_name') or ''), 'Inventory', guild_id=selected_guild_id)
            for item in inventory:
                item_name = validate_item_name((item or {}).get('item_name'))
                quantity = validate_item_quantity((item or {}).get('quantity'))
                if quantity == 0:
                    continue
                upsert_inventory_item(user_id, item_name, quantity, 'Inventory', guild_id=selected_guild_id)

        return jsonify({
            'status': 'success',
            'currency': fetch_currency_amount(user_id, 'Currency', guild_id=selected_guild_id),
            'inventory': fetch_inventory_items(user_id, 'Inventory', guild_id=selected_guild_id),
        })
    except ValueError as e:
        return api_error_response('Invalid request data.', 400, e)
    except Exception as e:
        return api_error_response('Internal server error.', 500, e)


@app.route('/api/users/<user_id>/characters/<sheet_id>', methods=['GET'])
def get_character_detail(user_id, sheet_id):
    """Get a character sheet's fields plus character-specific currency and inventory."""
    if not _USER_ID_RE.fullmatch(user_id):
        return jsonify({"error": "Invalid user ID"}), 400
    if not _SHEET_ID_RE.fullmatch(sheet_id):
        return jsonify({"error": "Invalid sheet ID"}), 400

    try:
        selected_guild_id = get_selected_server_id_required()
        if not sheet_matches_selected_server(user_id, sheet_id, selected_guild_id):
            return jsonify({"error": "Character not found"}), 404
        detail = build_sheet_detail_payload(user_id, sheet_id, guild_id=selected_guild_id)
        if not can_view_sheet_status(user_id, detail.get('status')):
            return jsonify({"error": "Character not found"}), 404
        return jsonify(detail)
    except FileNotFoundError:
        return jsonify({"error": "User not found"}), 404
    except sqlite3.OperationalError:
        return jsonify({"error": "Character not found"}), 404
    except Exception as e:
        return api_error_response('Internal server error.', 500, e)


@app.route('/api/users/<user_id>/characters/<sheet_id>/resources', methods=['POST'])
def update_character_resources(user_id, sheet_id):
    """Update a character's currency and inventory."""
    if role_is_member():
        return jsonify({"error": "Members can view inventory but cannot edit it."}), 403
    if not _USER_ID_RE.fullmatch(user_id):
        return jsonify({"error": "Invalid user ID"}), 400
    if not _SHEET_ID_RE.fullmatch(sheet_id):
        return jsonify({"error": "Invalid sheet ID"}), 400

    data = request.json or {}
    try:
        selected_guild_id = get_selected_server_id_required()
        if not sheet_matches_selected_server(user_id, sheet_id, selected_guild_id):
            return jsonify({"error": "Character not found"}), 404
        fetch_sheet_rows(user_id, sheet_id)

        if 'currency' in data:
            set_currency_amount(user_id, parse_currency_amount(data.get('currency')), sheet_id, guild_id=selected_guild_id)

        if 'inventory' in data:
            inventory = data.get('inventory') or []
            if not isinstance(inventory, list):
                raise ValueError('Inventory must be a list')

            # Replace full character-scope inventory with submitted values.
            for row in fetch_inventory_items(user_id, sheet_id, guild_id=selected_guild_id):
                delete_inventory_item(user_id, str(row.get('item_name') or ''), sheet_id, guild_id=selected_guild_id)
            for item in inventory:
                item_name = validate_item_name((item or {}).get('item_name'))
                quantity = validate_item_quantity((item or {}).get('quantity'))
                if quantity == 0:
                    continue
                upsert_inventory_item(user_id, item_name, quantity, sheet_id, guild_id=selected_guild_id)

        return jsonify(build_sheet_detail_payload(user_id, sheet_id, guild_id=selected_guild_id))
    except ValueError as e:
        return api_error_response('Invalid request data.', 400, e)
    except FileNotFoundError:
        return jsonify({"error": "User not found"}), 404
    except sqlite3.OperationalError:
        return jsonify({"error": "Character not found"}), 404
    except Exception as e:
        return api_error_response('Internal server error.', 500, e)


@app.route('/api/users/<user_id>/characters/<sheet_id>/inventory/<path:item_name>', methods=['DELETE'])
def delete_character_inventory_item(user_id, sheet_id, item_name):
    """Delete a single character inventory item."""
    if role_is_member():
        return jsonify({"error": "Members can view inventory but cannot edit it."}), 403
    if not _USER_ID_RE.fullmatch(user_id):
        return jsonify({"error": "Invalid user ID"}), 400
    if not _SHEET_ID_RE.fullmatch(sheet_id):
        return jsonify({"error": "Invalid sheet ID"}), 400

    try:
        fetch_sheet_rows(user_id, sheet_id)
        selected_guild_id = get_selected_server_id_required()
        delete_inventory_item(user_id, validate_item_name(item_name), sheet_id, guild_id=selected_guild_id)
        return jsonify({'status': 'success', 'inventory': fetch_inventory_items(user_id, sheet_id, guild_id=selected_guild_id)})
    except ValueError as e:
        return api_error_response('Invalid request data.', 400, e)
    except FileNotFoundError:
        return jsonify({"error": "User not found"}), 404
    except sqlite3.OperationalError:
        return jsonify({"error": "Character not found"}), 404
    except Exception as e:
        return api_error_response('Internal server error.', 500, e)


@app.route('/api/users/<user_id>/sheets/<sheet_id>/icon', methods=['GET'])
def get_sheet_icon(user_id, sheet_id):
    """Serve a character sheet's icon image."""
    if not _USER_ID_RE.fullmatch(user_id):
        abort(400)
    if not _SHEET_ID_RE.fullmatch(sheet_id):
        abort(400)
    try:
        rows = fetch_sheet_rows(user_id, sheet_id)
        icon_value = next((v for k, v in rows if str(k).lower() == 'icon'), '')
        row = (icon_value,) if icon_value else None
    except Exception:
        abort(404)
    if not row or not row[0]:
        abort(404)
    icon_path = USERS_DIR / 'images' / user_id / row[0]
    if not icon_path.exists():
        abort(404)
    return send_file(str(icon_path))


@app.route('/api/users/<user_id>/sheets/<sheet_id>', methods=['PATCH'])
def edit_sheet_fields(user_id, sheet_id):
    """Edit sheet fields and force status back to Draft when changed."""
    if not _USER_ID_RE.fullmatch(user_id):
        return jsonify({"error": "Invalid user ID"}), 400
    if not _SHEET_ID_RE.fullmatch(sheet_id):
        return jsonify({"error": "Invalid sheet ID"}), 400
    if not can_edit_sheet_for_target(user_id):
        return jsonify({"error": "You can only edit your own sheets."}), 403

    payload = request.json or {}
    updates = payload.get('updates')
    if not isinstance(updates, dict) or not updates:
        return jsonify({"error": "Provide updates as an object of field/value pairs."}), 400

    normalized_updates = []
    for raw_field, raw_value in updates.items():
        field_name = str(raw_field or '').strip()
        if not field_name:
            continue
        if field_name.lower() == 'status':
            continue
        value = '' if raw_value is None else str(raw_value)
        normalized_updates.append((field_name, value))

    if not normalized_updates:
        return jsonify({"error": "No editable fields provided."}), 400

    try:
        storage_sheet_id = _resolve_storage_sheet_id(user_id, sheet_id)
        if storage_sheet_id is None:
            return jsonify({"error": "Character not found"}), 404
        conn = sqlite3.connect(str(SHEETS_DB))
        c = conn.cursor()
        now_ts = int(utc_now().timestamp())

        for field_name, field_value in normalized_updates:
            c.execute('SELECT 1 FROM sheet_fields WHERE sheet_id=? AND field_name=? LIMIT 1', (int(storage_sheet_id), field_name))
            if c.fetchone():
                c.execute(
                    'UPDATE sheet_fields SET value=?, updated_at=? WHERE sheet_id=? AND field_name=?',
                    (field_value, now_ts, int(storage_sheet_id), field_name),
                )
            else:
                c.execute('SELECT COALESCE(MAX(sort_order), -1) + 1 FROM sheet_fields WHERE sheet_id=?', (int(storage_sheet_id),))
                next_order = int((c.fetchone() or [0])[0] or 0)
                c.execute(
                    'INSERT INTO sheet_fields (sheet_id, field_name, value, sort_order, updated_at) VALUES (?, ?, ?, ?, ?)',
                    (int(storage_sheet_id), field_name, field_value, next_order, now_ts),
                )

        c.execute('UPDATE sheets SET status=?, updated_at=? WHERE sheet_id=?', ('Draft', now_ts, int(storage_sheet_id)))
        conn.commit()
        conn.close()
        updated_rows = fetch_sheet_rows(user_id, sheet_id)
    except sqlite3.OperationalError:
        return jsonify({"error": "Character not found"}), 404
    except Exception as e:
        return api_error_response('Internal server error.', 500, e)

    # Keep metadata in sync.
    if SETTINGS_DB.exists():
        try:
            now_ts = int(utc_now().timestamp())
            sheet_name = next(
                (str(value) for field_name, value in updated_rows if str(field_name) == 'Name' and value is not None),
                None,
            ) or sheet_id
            conn = sqlite3.connect(str(SETTINGS_DB))
            conn.execute(
                'UPDATE SheetIndex SET sheet_name=?, status=?, updated_at=? WHERE user_id=? AND sheet_id=?',
                (sheet_name, 'Draft', now_ts, user_id, sheet_id)
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    selected_guild_id = get_selected_server_id_required()
    detail = build_sheet_detail_payload(user_id, sheet_id, guild_id=selected_guild_id)
    return jsonify(detail)


@app.route('/api/users/<user_id>/sheets/<sheet_id>', methods=['DELETE'])
def delete_sheet(user_id, sheet_id):
    """Delete a sheet with ownership and admin confirmation rules.

    Any items in the character's inventory are looked up in the shop price list
    and refunded as currency to the user's account-level wallet before deletion.
    Items with no shop entry are refunded at 0 (ignored).
    """
    if not _USER_ID_RE.fullmatch(user_id):
        return jsonify({"error": "Invalid user ID"}), 400
    if not _SHEET_ID_RE.fullmatch(sheet_id):
        return jsonify({"error": "Invalid sheet ID"}), 400
    if not can_delete_sheet_for_target(user_id):
        return jsonify({"error": "You can only delete your own sheets."}), 403

    body = request.json if isinstance(request.json, dict) else {}
    confirm_text = str(body.get('confirm_text') or '')
    if requires_admin_delete_confirm(user_id) and confirm_text != 'Confirm':
        return jsonify({"error": 'Deleting another member sheet requires typing exactly "Confirm".'}), 400

    icon_filename = None
    try:
        rows = fetch_sheet_rows(user_id, sheet_id)
        icon_row = next((v for k, v in rows if str(k).lower() == 'icon'), '')
        if icon_row:
            icon_filename = str(icon_row).strip()

        storage_sheet_id = _resolve_storage_sheet_id(user_id, sheet_id)
        if storage_sheet_id is None:
            return jsonify({"error": "Character not found"}), 404

        # --- Refund inventory items as currency ---
        try:
            # Resolve the character key used in Inventory.db for this sheet.
            character_key = _resolve_character_key(user_id, sheet_id, 'Currency')
            selected_guild_id = get_selected_server_id_required()
            refund_guild_id = selected_guild_id

            # Fetch all inventory rows for this character.
            inv_conn = sqlite3.connect(str(INVENTORY_DB))
            try:
                ensure_inventory_table(inv_conn, sheet_id)
                inv_rows = inv_conn.execute(
                    'SELECT item_name, quantity FROM inventory WHERE user_id=? AND guild_id=? AND character=?',
                    (str(user_id), str(refund_guild_id), character_key),
                ).fetchall()
            finally:
                inv_conn.close()

            if inv_rows:
                # Build item -> price lookup from the selected server shop.
                price_map = {}
                ensure_server_scoped_dashboard_schema(selected_guild_id)
                if SHOP_DB.exists():
                    shop_conn = sqlite3.connect(str(SHOP_DB))
                    try:
                        for item_name, price in shop_conn.execute(
                            'SELECT item_name, price FROM shop WHERE guild_id=?',
                            (selected_guild_id,),
                        ).fetchall():
                            price_map[str(item_name).strip().lower()] = float(price or 0)
                    finally:
                        shop_conn.close()

                refund_total = sum(
                    price_map.get(str(item_name).strip().lower(), 0) * int(qty or 0)
                    for item_name, qty in inv_rows
                )

                if refund_total > 0:
                    current = fetch_currency_amount(user_id, 'Currency', guild_id=selected_guild_id)
                    set_currency_amount(user_id, current + refund_total, 'Currency', guild_id=selected_guild_id)

                # Remove inventory rows for this character.
                del_conn = sqlite3.connect(str(INVENTORY_DB))
                try:
                    del_conn.execute(
                        'DELETE FROM inventory WHERE user_id=? AND guild_id=? AND character=?',
                        (str(user_id), str(refund_guild_id), character_key),
                    )
                    del_conn.commit()
                finally:
                    del_conn.close()
        except Exception:
            pass  # Refund is best-effort; don't block the deletion.

        conn = sqlite3.connect(str(SHEETS_DB))
        c = conn.cursor()
        c.execute(
            '''DELETE FROM sheets
               WHERE sheet_id=?
                 AND character_id IN (SELECT character_id FROM characters WHERE user_id=?)''',
            (int(storage_sheet_id), str(user_id)),
        )
        # Clean up characters with no remaining sheets.
        c.execute(
            '''DELETE FROM characters
               WHERE user_id=?
                 AND character_id NOT IN (SELECT character_id FROM sheets)''',
            (str(user_id),),
        )
        conn.commit()
        conn.close()
    except sqlite3.OperationalError:
        return jsonify({"error": "Character not found"}), 404
    except Exception as e:
        return api_error_response('Internal server error.', 500, e)

    if SETTINGS_DB.exists():
        try:
            conn = sqlite3.connect(str(SETTINGS_DB))
            conn.execute('DELETE FROM SheetIndex WHERE user_id=? AND sheet_id=?', (user_id, sheet_id))
            conn.commit()
            conn.close()
        except Exception:
            pass

    if icon_filename:
        try:
            icon_path = USERS_DIR / 'images' / user_id / icon_filename
            if icon_path.exists():
                icon_path.unlink()
        except Exception:
            pass

    return jsonify({"status": "success"})


def _send_import_notification(user_id, sheet_id, sheet_name, sheet_rows, storage_sheet_id=None, guild_id=None):
    """Post a 'Backup Imported' embed to the admin channel so staff can review it (best-effort)."""
    try:
        token = get_discord_bot_token()
        if not token:
            return

        admin_channel_id = None
        selected_guild_id = str(guild_id or '').strip()
        if SETTINGS_DB.exists():
            try:
                conn = sqlite3.connect(str(SETTINGS_DB))
                c = conn.cursor()
                if selected_guild_id:
                    c.execute('SELECT admin_channel_id FROM Server WHERE CAST(guild_id AS TEXT)=? LIMIT 1', (selected_guild_id,))
                else:
                    c.execute('SELECT admin_channel_id FROM Server LIMIT 1')
                row = c.fetchone()
                conn.close()
                if row and row[0]:
                    admin_channel_id = int(row[0])
            except Exception:
                pass

        if not admin_channel_id:
            return

        username = f'User {user_id}'
        if SETTINGS_DB.exists():
            try:
                conn = sqlite3.connect(str(SETTINGS_DB))
                c = conn.cursor()
                c.execute('SELECT username FROM UserProfile WHERE user_id=?', (user_id,))
                prow = c.fetchone()
                conn.close()
                if prow and prow[0]:
                    username = prow[0]
            except Exception:
                pass

        discord_fields = [
            {"name": "Character Name", "value": sheet_name[:1024], "inline": False},
            {"name": "Status", "value": "Imported from backup", "inline": False},
        ]
        for fname, fval in sheet_rows:
            if str(fname).lower() in ('name', 'status', 'icon') or not fval:
                continue
            fval = str(fval)
            while fval:
                discord_fields.append({"name": fname, "value": fval[:1024], "inline": False})
                fval = fval[1024:]
                fname = f"{fname} (cont.)"

        embeds = []
        for i in range(0, max(len(discord_fields), 1), 25):
            chunk = discord_fields[i:i + 25]
            embeds.append({
                "title": "Sheet Submission: Imported from Backup" if i == 0 else "Sheet Submission (continued)",
                "color": 10181046,  # purple
                "fields": chunk,
            })
        if embeds:
            embeds[0]["footer"] = {"text": f"User: {username}"}

        # Action buttons â€” custom_id encodes action:storage_sheet_id:user_id so the
        # bot's on_interaction handler can resolve and apply the review.
        sid_str = str(int(storage_sheet_id)) if storage_sheet_id else '0'
        components = [
            {
                "type": 1,  # Action Row
                "components": [
                    {"type": 2, "style": 3, "label": "Approve",
                     "custom_id": f"import_rev:approve:{sid_str}:{user_id}"},
                    {"type": 2, "style": 4, "label": "Deny",
                     "custom_id": f"import_rev:deny:{sid_str}:{user_id}"},
                    {"type": 2, "style": 1, "label": "Discuss",
                     "custom_id": f"import_rev:discuss:{sid_str}:{user_id}"},
                ],
            }
        ] if storage_sheet_id else []

        payload = json.dumps({
            "content": f"<@{user_id}> has imported a character sheet from backup.",
            "embeds": embeds[:10],
            "components": components,
        }).encode('utf-8')

        req = urllib_request.Request(
            f'https://discord.com/api/v10/channels/{admin_channel_id}/messages',
            data=payload,
            headers={
                'Authorization': f'Bot {token}',
                'Content-Type': 'application/json',
                'User-Agent': 'DiscordBotAdminDashboard/1.0',
            },
            method='POST',
        )
        with urllib_request.urlopen(req, timeout=10):
            pass
    except Exception:
        pass  # Notification is best-effort; don't fail the import.


def _notify_discord_status_change(user_id, sheet_id, new_status, sheet_rows, comment, guild_id=None):
    """Post a status-change embed to the member Discord channel (best-effort)."""
    try:
        token = get_discord_bot_token()
        if not token:
            return False, 'DISCORD_TOKEN is not configured for Online_Web_Server process.'

        member_channel_id = None
        selected_guild_id = str(guild_id or '').strip()
        if SETTINGS_DB.exists():
            try:
                conn = sqlite3.connect(str(SETTINGS_DB))
                c = conn.cursor()
                if selected_guild_id:
                    c.execute('SELECT member_channel_id FROM Server WHERE CAST(guild_id AS TEXT)=? LIMIT 1', (selected_guild_id,))
                else:
                    c.execute('SELECT member_channel_id FROM Server LIMIT 1')
                row = c.fetchone()
                conn.close()
                if row:
                    member_channel_id = row[0]
            except Exception:
                pass

        if not member_channel_id:
            return False, 'member_channel_id is not configured in Server table.'

        color_map = {'Approved': 3066993, 'Denied': 15158332, 'Discuss': 16776960}
        title_map = {
            'Approved': 'Sheet Approved',
            'Denied':   'Sheet Denied',
            'Discuss':  'Please Contact Staff',
        }
        color = color_map.get(new_status, 9807270)
        title = title_map.get(new_status, f'Sheet {new_status}')

        field_dict = {str(r[0]): (r[1] or '') for r in sheet_rows}
        field_dict_ci = {k.lower(): v for k, v in field_dict.items()}

        username = f'User {user_id}'
        if SETTINGS_DB.exists():
            try:
                conn = sqlite3.connect(str(SETTINGS_DB))
                c = conn.cursor()
                c.execute('SELECT username FROM UserProfile WHERE user_id=?', (user_id,))
                prow = c.fetchone()
                conn.close()
                if prow and prow[0]:
                    username = prow[0]
            except Exception:
                pass

        discord_fields = []
        status_value = new_status
        name_value = field_dict.get('Name') or field_dict_ci.get('name', '')
        if status_value:
            discord_fields.append({"name": "Status", "value": str(status_value)[:1024], "inline": False})
        if name_value:
            discord_fields.append({"name": "Name", "value": str(name_value)[:1024], "inline": False})
        for fname, fval in sheet_rows:
            if str(fname).lower() in ('status', 'name', 'icon') or not fval:
                continue
            fval = str(fval)
            while fval:
                discord_fields.append({"name": fname, "value": fval[:1024], "inline": False})
                fval = fval[1024:]
                fname = f"{fname} (cont.)"
        if comment:
            discord_fields.append({"name": "Moderator Comment", "value": comment[:1024], "inline": False})

        embeds = []
        for i in range(0, max(len(discord_fields), 1), 25):
            chunk = discord_fields[i:i + 25]
            embeds.append({
                "title": title if i == 0 else f"{title} (continued)",
                "color": color,
                "fields": chunk,
            })
        if embeds:
            embeds[0]["footer"] = {"text": f"User: {username}"}

        payload = json.dumps({
            "content": f"<@{user_id}>",
            "embeds": embeds[:10],
        }).encode('utf-8')

        req = urllib_request.Request(
            f'https://discord.com/api/v10/channels/{member_channel_id}/messages',
            data=payload,
            headers={
                'Authorization': f'Bot {token}',
                'Content-Type': 'application/json',
                'User-Agent': 'DiscordBotAdminDashboard/1.0',
            },
            method='POST',
        )
        with urllib_request.urlopen(req, timeout=10):
            pass
        return True, None
    except Exception as e:
        return False, str(e)


def _close_admin_review_embed(user_id, sheet_id, sheet_rows, guild_id=None):
    """Disable buttons on the admin review message after a website action."""
    try:
        token = get_discord_bot_token()
        if not token:
            return False, 'DISCORD_TOKEN is not configured for Online_Web_Server process.'

        def _auth_headers(with_json=False):
            headers = {
                'Authorization': f'Bot {token}',
                'User-Agent': 'DiscordBotAdminDashboard/1.0',
            }
            if with_json:
                headers['Content-Type'] = 'application/json'
            return headers

        def _remove_components(channel_id, message_id):
            patch_payload = json.dumps({'components': []}).encode('utf-8')
            patch_req = urllib_request.Request(
                f'https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}',
                data=patch_payload,
                headers=_auth_headers(with_json=True),
                method='PATCH',
            )
            with urllib_request.urlopen(patch_req, timeout=10):
                pass

            # Verify component removal to avoid false positives.
            get_req = urllib_request.Request(
                f'https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}',
                headers=_auth_headers(),
            )
            with urllib_request.urlopen(get_req, timeout=10) as resp:
                msg = json.loads(resp.read().decode('utf-8'))
            return not bool(msg.get('components'))

        def _message_matches_review(msg, target_name, target_username):
            if not msg.get('components'):
                return False

            embeds = msg.get('embeds') or []
            if not embeds:
                return False

            first_title = str((embeds[0] or {}).get('title') or '').strip().lower()
            if 'sheet submission' not in first_title:
                return False

            name_match = False
            footer_match = False

            for emb in embeds:
                footer_text = str((emb.get('footer') or {}).get('text') or '').strip().lower()
                if target_username and footer_text == f'user: {target_username}':
                    footer_match = True

                for field in emb.get('fields', []) or []:
                    field_name = str(field.get('name', '')).strip().lower()
                    field_value = str(field.get('value', '')).strip().lower()
                    if field_name == 'name' and target_name and field_value == target_name:
                        name_match = True

            # Prefer exact character-name match; footer is a secondary signal.
            if target_name and target_username:
                return name_match and footer_match
            if target_name:
                return name_match
            if target_username:
                return footer_match
            return False

        review_channel_id = None
        review_message_id = None
        admin_channel_id = None
        target_username = ''

        conn = sqlite3.connect(str(SETTINGS_DB))
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS Server (
            guild_id INTEGER PRIMARY KEY,
            admin_role_id INTEGER,
            admin_channel_id INTEGER,
            member_role_id INTEGER,
            member_channel_id INTEGER
        )''')
        selected_guild_id = str(guild_id or '').strip()
        if selected_guild_id:
            c.execute('SELECT admin_channel_id FROM Server WHERE CAST(guild_id AS TEXT)=? LIMIT 1', (selected_guild_id,))
        else:
            c.execute('SELECT admin_channel_id FROM Server LIMIT 1')
        server_row = c.fetchone()
        if server_row and server_row[0]:
            admin_channel_id = int(server_row[0])

        c.execute('''CREATE TABLE IF NOT EXISTS SheetIndex (
            user_id TEXT NOT NULL,
            guild_id INTEGER,
            sheet_id TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            review_channel_id INTEGER,
            review_message_id INTEGER,
            PRIMARY KEY (user_id, sheet_id)
        )''')
        c.execute('PRAGMA table_info(SheetIndex)')
        columns = {row[1] for row in c.fetchall()}
        if 'review_channel_id' not in columns:
            c.execute('ALTER TABLE SheetIndex ADD COLUMN review_channel_id INTEGER')
        if 'review_message_id' not in columns:
            c.execute('ALTER TABLE SheetIndex ADD COLUMN review_message_id INTEGER')
        c.execute(
            'SELECT review_channel_id, review_message_id FROM SheetIndex WHERE user_id=? AND sheet_id=?',
            (user_id, sheet_id)
        )
        row = c.fetchone()
        c.execute('SELECT username FROM UserProfile WHERE user_id=?', (user_id,))
        user_row = c.fetchone()
        if user_row and user_row[0]:
            target_username = str(user_row[0]).strip().lower()
        conn.commit()
        conn.close()

        if row and row[0] and row[1]:
            review_channel_id = int(row[0])
            review_message_id = int(row[1])

        # Prefer tracked message first.
        if review_channel_id and review_message_id:
            try:
                if _remove_components(review_channel_id, review_message_id):
                    try:
                        conn = sqlite3.connect(str(SETTINGS_DB))
                        conn.execute(
                            'UPDATE SheetIndex SET review_channel_id=NULL, review_message_id=NULL WHERE user_id=? AND sheet_id=?',
                            (user_id, sheet_id)
                        )
                        conn.commit()
                        conn.close()
                    except Exception:
                        pass
                    return True, None
            except Exception:
                # Fallback scan below will try to recover.
                pass

        # Fallback for older records before message tracking existed
        if admin_channel_id:
            target_name = ''
            for fname, fval in sheet_rows:
                if str(fname).lower() == 'name' and fval:
                    target_name = str(fval).strip().lower()
                    break

            list_req = urllib_request.Request(
                f'https://discord.com/api/v10/channels/{admin_channel_id}/messages?limit=100',
                headers=_auth_headers(),
            )
            with urllib_request.urlopen(list_req, timeout=10) as resp:
                recent_messages = json.loads(resp.read().decode('utf-8'))

            closed_any = False
            for msg in recent_messages:
                if not _message_matches_review(msg, target_name, target_username):
                    continue
                try:
                    if _remove_components(int(admin_channel_id), int(msg['id'])):
                        closed_any = True
                except Exception:
                    continue

            if closed_any:
                try:
                    conn = sqlite3.connect(str(SETTINGS_DB))
                    conn.execute(
                        'UPDATE SheetIndex SET review_channel_id=NULL, review_message_id=NULL WHERE user_id=? AND sheet_id=?',
                        (user_id, sheet_id)
                    )
                    conn.commit()
                    conn.close()
                except Exception:
                    pass
                return True, None

        return False, 'Unable to find and close an active admin review embed for this sheet.'
    except Exception as e:
        return False, str(e)


@app.route('/api/users/<user_id>/sheets/<sheet_id>/status', methods=['POST'])
def set_sheet_status(user_id, sheet_id):
    """Change a character sheet's status and notify the user via their member channel."""
    if role_is_member():
        return jsonify({"error": "Members cannot change moderation status from the website."}), 403
    if not _USER_ID_RE.fullmatch(user_id):
        return jsonify({"error": "Invalid user ID"}), 400
    if not _SHEET_ID_RE.fullmatch(sheet_id):
        return jsonify({"error": "Invalid sheet ID"}), 400
    data = request.json or {}
    new_status = str(data.get('status', '')).strip()
    comment = str(data.get('comment', '') or '').strip()
    _ACTION_STATUSES = {'Approved', 'Denied', 'Discuss', 'Imported'}
    if new_status not in _ACTION_STATUSES:
        return jsonify({"error": f"Invalid status. Must be one of: {', '.join(sorted(_ACTION_STATUSES))}"}), 400

    try:
        selected_guild_id = get_selected_server_id_required()
    except ValueError as e:
        return api_error_response('Invalid request data.', 400, e)

    updated_rows = []
    try:
        storage_sheet_id = _resolve_storage_sheet_id(user_id, sheet_id)
        if storage_sheet_id is None:
            return jsonify({"error": "Sheet not found"}), 404

        conn = sqlite3.connect(str(SHEETS_DB))
        c = conn.cursor()
        c.execute(
            '''SELECT s.status
               FROM sheets s
               JOIN characters c ON c.character_id=s.character_id
               WHERE s.sheet_id=? AND c.user_id=?
               LIMIT 1''',
            (int(storage_sheet_id), str(user_id)),
        )
        status_row = c.fetchone()
        current_status = str(status_row[0]).strip() if status_row and status_row[0] is not None else ''
        if current_status in {'Approved', 'Denied'}:
            conn.close()
            return jsonify({
                "error": f"This sheet was already {current_status.lower()}. Refresh the page to see the latest state.",
                "current_status": current_status,
            }), 409

        c.execute('UPDATE sheets SET status=?, updated_at=? WHERE sheet_id=?', (new_status, int(utc_now().timestamp()), int(storage_sheet_id)))
        conn.commit()
        conn.close()
        updated_rows = fetch_sheet_rows(user_id, sheet_id)
    except sqlite3.OperationalError:
        return jsonify({"error": "Sheet not found"}), 404
    except Exception as e:
        return api_error_response('Internal server error.', 500, e)

    # Update SheetIndex metadata
    if SETTINGS_DB.exists():
        try:
            import time as _time
            conn = sqlite3.connect(str(SETTINGS_DB))
            conn.execute('PRAGMA journal_mode = WAL')
            conn.execute(
                'UPDATE SheetIndex SET status=?, updated_at=? WHERE user_id=? AND sheet_id=?',
                (new_status, int(_time.time()), user_id, sheet_id)
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    # Send Discord member-channel notification (mirrors bot on_action behaviour)
    notification_sent, notification_error = _notify_discord_status_change(
        user_id, sheet_id, new_status, updated_rows, comment, guild_id=selected_guild_id
    )

    review_closed, review_close_error = _close_admin_review_embed(user_id, sheet_id, updated_rows, guild_id=selected_guild_id)

    response = {
        "status": "success",
        "new_status": new_status,
        "notification_sent": bool(notification_sent),
        "review_embed_closed": bool(review_closed),
    }
    if notification_error:
        response["notification_error"] = notification_error
    if review_close_error:
        response["review_embed_close_error"] = review_close_error
    return jsonify(response)


@app.route('/api/users/<user_id>/sheets/<sheet_id>/export', methods=['GET'])
def export_sheet(user_id, sheet_id):
    """Export a character sheet as JSON.

    Members may only export their own sheets.  Admins and owners may export any sheet.
    """
    if not _USER_ID_RE.fullmatch(user_id):
        return jsonify({"error": "Invalid user ID"}), 400
    if not _SHEET_ID_RE.fullmatch(sheet_id):
        return jsonify({"error": "Invalid sheet ID"}), 400
    session_uid = current_session_user_id()
    role = current_session_role()
    if session_uid != user_id and role_is_member(role):
        return jsonify({"error": "Members can only export their own sheets."}), 403

    try:
        selected_guild_id = get_selected_server_id_required()
        detail = build_sheet_detail_payload(user_id, sheet_id, guild_id=selected_guild_id)
        # Strip Name/Status from the fields list â€” they are already top-level keys.
        _reserved = {'name', 'status'}
        clean_fields = [
            f for f in detail.get('fields', [])
            if str(f.get('field_name', '')).strip().lower() not in _reserved
        ]
        export_data = {
            'sheet_id': sheet_id,
            'sheet_name': detail.get('sheet_name'),
            'fields': clean_fields,
        }
        return jsonify(export_data)
    except FileNotFoundError:
        return jsonify({"error": "User not found"}), 404
    except sqlite3.OperationalError:
        return jsonify({"error": "Character not found"}), 404
    except Exception as e:
        return api_error_response('Internal server error.', 500, e)


@app.route('/api/users/<user_id>/sheets/import', methods=['POST'])
def import_sheet(user_id):
    """Import a character sheet from a backup JSON file (fields only, no currency/inventory)."""
    if not _USER_ID_RE.fullmatch(user_id):
        return jsonify({"error": "Invalid user ID"}), 400
    if current_session_user_id() != user_id:
        return jsonify({"error": "You can only import sheets into your own account."}), 403

    try:
        selected_guild_id = get_selected_server_id_required()
    except ValueError as e:
        return api_error_response('Invalid request data.', 400, e)

    try:
        import_data = request.json or {}
        sheet_name = str(import_data.get('sheet_name', 'Imported Sheet')).strip()
        if not sheet_name:
            sheet_name = 'Imported Sheet'

        fields = import_data.get('fields', [])
        if not isinstance(fields, list):
            fields = []

        # Validate fields â€” ignore currency, inventory, status, name, icon.
        reserved_field_names = {'name', 'status', 'icon'}
        validated_fields = []
        seen_field_names = set()
        for field in fields:
            if isinstance(field, dict):
                field_name = str(field.get('field_name', '')).strip()
                data = str(field.get('data', '')).strip()
                field_key = field_name.lower()
                if not field_name or field_key in reserved_field_names or field_key in seen_field_names:
                    continue
                seen_field_names.add(field_key)
                validated_fields.append({'field_name': field_name, 'data': data})

        # Prefer exported sheet ID when valid and unused, else generate a fresh one.
        import uuid as _uuid
        requested_sheet_id = str(import_data.get('sheet_id', '')).strip().upper()

        ensure_sheet_storage_schema()
        ensure_sheet_index_schema()
        conn = sqlite3.connect(str(SETTINGS_DB))
        c = conn.cursor()

        new_sheet_id = None
        candidate_ids = []
        if requested_sheet_id and _SHEET_ID_RE.fullmatch(requested_sheet_id):
            candidate_ids.append(requested_sheet_id)
        for _ in range(8):
            candidate_ids.append(_uuid.uuid4().hex[:6].upper())

        seen_candidate_ids = set()
        for candidate_id in candidate_ids:
            if candidate_id in seen_candidate_ids:
                continue
            seen_candidate_ids.add(candidate_id)
            exists = c.execute(
                "SELECT 1 FROM SheetIndex WHERE user_id=? AND sheet_id=? LIMIT 1",
                (str(user_id), candidate_id),
            ).fetchone()
            if not exists:
                new_sheet_id = candidate_id
                break
        if not new_sheet_id:
            conn.close()
            return jsonify({"error": "Unable to allocate a unique sheet ID"}), 500

        conn_sheets = sqlite3.connect(str(SHEETS_DB))
        cur = conn_sheets.cursor()
        now_ts = int(utc_now().timestamp())
        guild_id_for_import = str(selected_guild_id)
        import_status = 'Imported'

        actual_name = sheet_name
        suffix = 2
        character_id = None
        while character_id is None:
            try:
                cur.execute(
                    'INSERT INTO characters (user_id, guild_id, name, created_at) VALUES (?, ?, ?, ?)',
                    (str(user_id), guild_id_for_import, actual_name, now_ts),
                )
                character_id = int(cur.lastrowid)
            except sqlite3.IntegrityError:
                actual_name = f"{sheet_name} ({suffix})"
                suffix += 1

        cur.execute(
            'INSERT INTO sheets (character_id, status, created_at, updated_at) VALUES (?, ?, ?, ?)',
            (int(character_id), import_status, now_ts, now_ts),
        )
        storage_sheet_id = int(cur.lastrowid)

        sort_order = 0
        for field in validated_fields:
            cur.execute(
                'INSERT INTO sheet_fields (sheet_id, field_name, value, sort_order, updated_at) VALUES (?, ?, ?, ?, ?)',
                (int(storage_sheet_id), field['field_name'], field['data'], sort_order, now_ts),
            )
            sort_order += 1
        conn_sheets.commit()
        conn_sheets.close()

        c.execute(
            'INSERT OR REPLACE INTO SheetIndex (user_id, guild_id, sheet_id, sheet_name, status, created_at, updated_at, storage_sheet_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (str(user_id), int(selected_guild_id), new_sheet_id, actual_name, import_status, now_ts, now_ts, int(storage_sheet_id)),
        )
        conn.commit()
        conn.close()

        # Notify the admin channel so staff are aware of the restored backup.
        sheet_rows = fetch_sheet_rows(user_id, new_sheet_id)
        _send_import_notification(
            user_id,
            new_sheet_id,
            actual_name,
            sheet_rows,
            storage_sheet_id,
            guild_id=selected_guild_id,
        )

        return jsonify({
            "status": "success",
            "sheet_id": new_sheet_id,
            "sheet_name": actual_name,
            "message": "Sheet imported from backup. Staff have been notified for review.",
        })

    except Exception as e:
        return api_error_response('Internal server error.', 500, e)


@app.route('/api/users/<user_id>/sheets/new', methods=['POST'])
def create_sheet(user_id):
    """Create a brand-new Draft sheet for the current selected server."""
    if not _USER_ID_RE.fullmatch(user_id):
        return jsonify({"error": "Invalid user ID"}), 400
    if current_session_user_id() != user_id:
        return jsonify({"error": "You can only create sheets in your own account."}), 403

    try:
        selected_guild_id = get_selected_server_id_required()
    except ValueError as e:
        return api_error_response('Invalid request data.', 400, e)

    try:
        payload = request.json or {}
        requested_name = str(payload.get('sheet_name', 'New Character')).strip()
        if not requested_name:
            requested_name = 'New Character'

        import uuid as _uuid

        ensure_sheet_storage_schema()
        ensure_sheet_index_schema()
        conn = sqlite3.connect(str(SETTINGS_DB))
        c = conn.cursor()

        new_sheet_id = None
        seen_candidate_ids = set()
        for _ in range(12):
            candidate_id = _uuid.uuid4().hex[:6].upper()
            if candidate_id in seen_candidate_ids:
                continue
            seen_candidate_ids.add(candidate_id)
            exists = c.execute(
                'SELECT 1 FROM SheetIndex WHERE user_id=? AND sheet_id=? LIMIT 1',
                (str(user_id), candidate_id),
            ).fetchone()
            if not exists:
                new_sheet_id = candidate_id
                break

        if not new_sheet_id:
            conn.close()
            return jsonify({"error": "Unable to allocate a unique sheet ID"}), 500

        conn_sheets = sqlite3.connect(str(SHEETS_DB))
        cur = conn_sheets.cursor()
        now_ts = int(utc_now().timestamp())
        guild_id_for_sheet = str(selected_guild_id)
        sheet_status = 'Draft'

        actual_name = requested_name
        suffix = 2
        character_id = None
        while character_id is None:
            try:
                cur.execute(
                    'INSERT INTO characters (user_id, guild_id, name, created_at) VALUES (?, ?, ?, ?)',
                    (str(user_id), guild_id_for_sheet, actual_name, now_ts),
                )
                character_id = int(cur.lastrowid)
            except sqlite3.IntegrityError:
                actual_name = f"{requested_name} ({suffix})"
                suffix += 1

        cur.execute(
            'INSERT INTO sheets (character_id, status, created_at, updated_at) VALUES (?, ?, ?, ?)',
            (int(character_id), sheet_status, now_ts, now_ts),
        )
        storage_sheet_id = int(cur.lastrowid)
        conn_sheets.commit()
        conn_sheets.close()

        c.execute(
            'INSERT OR REPLACE INTO SheetIndex (user_id, guild_id, sheet_id, sheet_name, status, created_at, updated_at, storage_sheet_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (str(user_id), int(selected_guild_id), new_sheet_id, actual_name, sheet_status, now_ts, now_ts, int(storage_sheet_id)),
        )
        conn.commit()
        conn.close()

        return jsonify({
            'status': 'success',
            'sheet_id': new_sheet_id,
            'sheet_name': actual_name,
            'message': 'Draft sheet created.',
        })
    except Exception as e:
        return api_error_response('Internal server error.', 500, e)


@app.route('/api/servers/<guild_id>', methods=['GET'])
def get_server(guild_id):
    """Get server configuration"""
    if not role_is_admin():
        return jsonify({"error": "Admin role required for server configuration."}), 403
    try:
        ensure_settings_schema()
        guild_id = parse_snowflake(guild_id, 'Guild ID')
        guild_lookup = get_live_bot_guild_lookup()
        conn = get_db_connection(SETTINGS_DB)
        c = conn.cursor()
        c.execute('SELECT * FROM Server WHERE guild_id=?', (guild_id,))
        server = c.fetchone()
        conn.close()
        return jsonify(_serialize_server_row(server, guild_lookup) or {})
    except ValueError as e:
        return api_error_response('Invalid request data.', 400, e)
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

@app.route('/api/servers/<guild_id>', methods=['POST'])
def update_server(guild_id):
    """Update server configuration"""
    if not role_is_admin():
        return jsonify({"error": "Admin role required for server configuration changes."}), 403
    try:
        ensure_settings_schema()
        guild_id = parse_snowflake(guild_id, 'Guild ID')
        data = request.json
        conn = get_db_connection(SETTINGS_DB)
        c = conn.cursor()

        # Ensure table exists
        c.execute('''CREATE TABLE IF NOT EXISTS Server (
            guild_id INTEGER PRIMARY KEY,
            admin_role_id INTEGER,
            admin_channel_id INTEGER,
            member_role_id INTEGER,
            member_channel_id INTEGER
        )''')

        # Check if server exists
        c.execute('SELECT * FROM Server WHERE guild_id=?', (guild_id,))
        exists = c.fetchone()

        admin_role_id = parse_snowflake(data.get('admin_role_id'), 'Admin Role ID', required=False)
        admin_channel_id = parse_snowflake(data.get('admin_channel_id'), 'Admin Channel ID', required=False)
        member_role_id = parse_snowflake(data.get('member_role_id'), 'Member Role ID', required=False)
        member_channel_id = parse_snowflake(data.get('member_channel_id'), 'Member Channel ID', required=False)

        if exists:
            c.execute('''UPDATE Server SET
                admin_role_id=?, admin_channel_id=?,
                member_role_id=?, member_channel_id=?
                WHERE guild_id=?''',
                (admin_role_id, admin_channel_id,
                 member_role_id, member_channel_id, guild_id))
        else:
            c.execute('''INSERT INTO Server
                (guild_id, admin_role_id, admin_channel_id, member_role_id, member_channel_id)
                VALUES (?, ?, ?, ?, ?)''',
                (guild_id, admin_role_id, admin_channel_id,
                 member_role_id, member_channel_id))

        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except ValueError as e:
        return api_error_response('Invalid request data.', 400, e)
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

# --- Sheet Fields ---
@app.route('/api/servers/<guild_id>/fields', methods=['GET'])
def get_fields(guild_id):
    """Get sheet fields for server"""
    if not role_is_admin() and current_session_role() != ROLE_UNASSIGNED:
        return jsonify({"error": "Only admins can view server sheet fields."}), 403
    try:
        guild_id = parse_snowflake(guild_id, 'Guild ID')
        fields = list_guild_template_fields(guild_id)
        return jsonify(fields)
    except ValueError as e:
        return api_error_response('Invalid request data.', 400, e)
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

@app.route('/api/servers/<guild_id>/fields', methods=['POST'])
def add_field(guild_id):
    """Add sheet field"""
    if not role_is_admin() and current_session_role() != ROLE_UNASSIGNED:
        return jsonify({"error": "Only admins can add server sheet fields."}), 403
    try:
        guild_id = parse_snowflake(guild_id, 'Guild ID')
        data = request.json
        field_name = validate_admin_name(data.get('field_name', ''), 'Field name', 80)

        if not field_name:
            return jsonify({"error": "Field name required"}), 400
        if field_name.lower() in ["status", "name"]:
            return jsonify({"error": f'Cannot add permanent field "{field_name}"'}), 400

        add_guild_template_field(guild_id, field_name)
        return jsonify({"status": "success", "field": field_name})
    except ValueError as e:
        return api_error_response('Invalid request data.', 400, e)
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

@app.route('/api/servers/<guild_id>/fields/<field_name>', methods=['DELETE'])
def delete_field(guild_id, field_name):
    """Delete sheet field"""
    if not role_is_admin() and current_session_role() != ROLE_UNASSIGNED:
        return jsonify({"error": "Only admins can remove server sheet fields."}), 403
    try:
        guild_id = parse_snowflake(guild_id, 'Guild ID')
        if field_name.lower() in ["status", "name"]:
            return jsonify({"error": f'Cannot delete permanent field "{field_name}"'}), 400

        remove_guild_template_field(guild_id, field_name)
        return jsonify({"status": "success"})
    except ValueError as e:
        return api_error_response('Invalid request data.', 400, e)
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

# --- Shop Management ---
@app.route('/api/server-shop/catalog', methods=['GET'])
def get_server_shop_catalog():
    """Get member-facing server shop catalog and own sheets."""
    user_id = current_session_user_id()
    if not _USER_ID_RE.fullmatch(user_id):
        return jsonify({"error": "Authentication required"}), 401

    try:
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        # Load priced shop entries.
        conn = get_db_connection(SHOP_DB)
        c = conn.cursor()
        c.execute('SELECT item_name, price FROM shop WHERE guild_id=? ORDER BY item_name COLLATE NOCASE', (selected_guild_id,))
        shop_rows = c.fetchall() or []
        conn.close()

        # Load item metadata (description/image).
        item_meta = {}
        if ITEMS_DB.exists():
            conn = get_db_connection(ITEMS_DB)
            c = conn.cursor()
            c.execute('SELECT name, image, description FROM items WHERE guild_id=?', (selected_guild_id,))
            for row in c.fetchall() or []:
                item_name = str(row.get('name') or '').strip()
                if item_name:
                    item_meta[item_name] = {
                        'image': row.get('image'),
                        'description': row.get('description'),
                    }
            conn.close()

        items = []
        for row in shop_rows:
            item_name = str(row.get('item_name') or '').strip()
            if not item_name:
                continue
            try:
                price = int(row.get('price') or 0)
            except (TypeError, ValueError):
                price = 0
            if price < 0:
                price = 0

            meta = item_meta.get(item_name, {})
            has_image = bool(meta.get('image'))
            items.append(
                {
                    'item_name': item_name,
                    'price': price,
                    'description': str(meta.get('description') or '').strip(),
                    'has_image': has_image,
                    'image_url': f"/api/server-shop/items/{urllib_parse.quote(item_name)}/image" if has_image else None,
                }
            )

        # Own sheets to receive purchases.
        sheets = []
        if SETTINGS_DB.exists():
            conn = get_db_connection(SETTINGS_DB)
            c = conn.cursor()
            c.execute(
                '''CREATE TABLE IF NOT EXISTS SheetIndex (
                    user_id TEXT NOT NULL, guild_id INTEGER,
                    sheet_id TEXT NOT NULL, sheet_name TEXT NOT NULL,
                    status TEXT NOT NULL, created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL, PRIMARY KEY (user_id, sheet_id)
                )'''
            )
            c.execute(
                'SELECT sheet_id, sheet_name, status FROM SheetIndex WHERE user_id=? AND CAST(guild_id AS TEXT)=? ORDER BY sheet_name COLLATE NOCASE',
                (user_id, selected_guild_id)
            )
            for row in c.fetchall() or []:
                sheet_id = str(row.get('sheet_id') or '').strip()
                if not _SHEET_ID_RE.fullmatch(sheet_id):
                    continue
                sheets.append(
                    {
                        'sheet_id': sheet_id,
                        'sheet_name': str(row.get('sheet_name') or sheet_id),
                        'status': str(row.get('status') or 'Draft'),
                        'currency': fetch_currency_amount(user_id, sheet_id, guild_id=selected_guild_id),
                    }
                )
            conn.close()

        return jsonify(
            {
                'user_id': user_id,
                'role': current_session_role(),
                'can_purchase': True,
                'account_currency': fetch_currency_amount(user_id, 'Currency', guild_id=selected_guild_id),
                'sheets': sheets,
                'items': items,
            }
        )
    except Exception as e:
        return api_error_response('Internal server error.', 500, e)


@app.route('/api/server-shop/items/<item_name>/image', methods=['GET'])
def get_server_shop_item_image(item_name):
    """Get item image for member-facing server shop."""
    user_id = current_session_user_id()
    if not _USER_ID_RE.fullmatch(user_id):
        return jsonify({"error": "Authentication required"}), 401
    try:
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        conn = get_db_connection(ITEMS_DB)
        c = conn.cursor()
        c.execute('SELECT image FROM items WHERE guild_id=? AND name=?', (selected_guild_id, item_name))
        row = c.fetchone()
        conn.close()

        if not row or not row.get('image'):
            return jsonify({"error": "No image for item"}), 404

        images_dir = str(ITEMS_DIR)
        image_path = os.path.join(images_dir, row['image'])
        if not os.path.exists(image_path):
            return jsonify({"error": "Image not found"}), 404

        return send_file(image_path)
    except Exception as e:
        return api_error_response('Request failed.', 400, e)


@app.route('/api/server-shop/purchase', methods=['POST'])
def purchase_server_shop_item():
    """Purchase a shop item into one of the member's own sheets."""
    user_id = current_session_user_id()
    if not _USER_ID_RE.fullmatch(user_id):
        return jsonify({"error": "Authentication required"}), 401

    data = request.json or {}
    sheet_id = str(data.get('sheet_id') or '').strip()
    item_name = str(data.get('item_name') or '').strip()
    use_account_scope = not sheet_id
    target_table = 'Currency' if use_account_scope else sheet_id
    target_inventory_table = 'Inventory' if use_account_scope else sheet_id

    try:
        quantity = int(data.get('quantity', 1))
    except (TypeError, ValueError):
        return jsonify({"error": "Quantity must be a whole number."}), 400

    if (not use_account_scope) and (not _SHEET_ID_RE.fullmatch(sheet_id)):
        return jsonify({"error": "Invalid sheet ID."}), 400
    if not item_name:
        return jsonify({"error": "Item name is required."}), 400
    if quantity <= 0:
        return jsonify({"error": "Quantity must be at least 1."}), 400

    # Ensure the target sheet (when provided) belongs to current user and exists.
    if not use_account_scope:
        try:
            selected_guild_id = get_selected_server_id_required()
        except ValueError as e:
            return api_error_response('Invalid request data.', 400, e)
        if not sheet_matches_selected_server(user_id, sheet_id, selected_guild_id):
            return jsonify({"error": "Target sheet not found for selected server."}), 404
        try:
            fetch_sheet_rows(user_id, sheet_id)
        except FileNotFoundError:
            return jsonify({"error": "User not found."}), 404
        except sqlite3.OperationalError:
            return jsonify({"error": "Target sheet not found."}), 404

    try:
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        conn = get_db_connection(SHOP_DB)
        c = conn.cursor()
        c.execute('SELECT price FROM shop WHERE guild_id=? AND item_name=?', (selected_guild_id, item_name))
        price_row = c.fetchone()
        conn.close()
    except Exception as e:
        return api_error_response('Internal server error.', 500, e)

    if not price_row:
        return jsonify({"error": "Item is not available in the shop."}), 404

    try:
        price = int(price_row.get('price') or 0)
    except (TypeError, ValueError):
        price = 0
    if price < 0:
        price = 0

    total_cost = float(price * quantity)
    current_currency = fetch_currency_amount(user_id, target_table, guild_id=selected_guild_id)
    if current_currency < total_cost:
        return jsonify(
            {
                'error': f'Not enough currency. Required {total_cost:.2f}, available {current_currency:.2f}.'
            }
        ), 400

    # Deduct money and add quantity to target sheet inventory.
    new_currency = current_currency - total_cost
    set_currency_amount(user_id, new_currency, target_table, guild_id=selected_guild_id)

    existing_items = fetch_inventory_items(user_id, target_inventory_table, guild_id=selected_guild_id)
    current_qty = 0
    for row in existing_items:
        if str(row.get('item_name') or '') == item_name:
            try:
                current_qty = int(row.get('quantity') or 0)
            except (TypeError, ValueError):
                current_qty = 0
            break
    upsert_inventory_item(user_id, item_name, current_qty + quantity, target_inventory_table, guild_id=selected_guild_id)

    return jsonify(
        {
            'status': 'success',
            'message': f'Bought {quantity} x {item_name} for {total_cost:.2f}.',
            'currency': new_currency,
            'item_name': item_name,
            'quantity_added': quantity,
            'total_cost': total_cost,
            'sheet_id': sheet_id or None,
            'scope': 'account' if use_account_scope else 'sheet',
            'sheet_currency': new_currency,
        }
    )


@app.route('/api/server-shop/sell', methods=['POST'])
def sell_server_shop_item():
    """Sell a shop item from one of the member's own sheets."""
    user_id = current_session_user_id()
    if not _USER_ID_RE.fullmatch(user_id):
        return jsonify({"error": "Authentication required"}), 401

    data = request.json or {}
    sheet_id = str(data.get('sheet_id') or '').strip()
    item_name = str(data.get('item_name') or '').strip()
    use_account_scope = not sheet_id
    target_table = 'Currency' if use_account_scope else sheet_id
    target_inventory_table = 'Inventory' if use_account_scope else sheet_id

    try:
        quantity = int(data.get('quantity', 1))
    except (TypeError, ValueError):
        return jsonify({"error": "Quantity must be a whole number."}), 400

    if (not use_account_scope) and (not _SHEET_ID_RE.fullmatch(sheet_id)):
        return jsonify({"error": "Invalid sheet ID."}), 400
    if not item_name:
        return jsonify({"error": "Item name is required."}), 400
    if quantity <= 0:
        return jsonify({"error": "Quantity must be at least 1."}), 400

    # Ensure the target sheet (when provided) belongs to current user and exists.
    if not use_account_scope:
        try:
            selected_guild_id = get_selected_server_id_required()
        except ValueError as e:
            return api_error_response('Invalid request data.', 400, e)
        if not sheet_matches_selected_server(user_id, sheet_id, selected_guild_id):
            return jsonify({"error": "Target sheet not found for selected server."}), 404
        try:
            fetch_sheet_rows(user_id, sheet_id)
        except FileNotFoundError:
            return jsonify({"error": "User not found."}), 404
        except sqlite3.OperationalError:
            return jsonify({"error": "Target sheet not found."}), 404

    try:
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        conn = get_db_connection(SHOP_DB)
        c = conn.cursor()
        c.execute('SELECT price FROM shop WHERE guild_id=? AND item_name=?', (selected_guild_id, item_name))
        price_row = c.fetchone()
        conn.close()
    except Exception as e:
        return api_error_response('Internal server error.', 500, e)

    if not price_row:
        return jsonify({"error": "Item is not available in the shop."}), 404

    try:
        price = int(price_row.get('price') or 0)
    except (TypeError, ValueError):
        price = 0
    if price < 0:
        price = 0

    existing_items = fetch_inventory_items(user_id, target_inventory_table, guild_id=selected_guild_id)
    current_qty = 0
    for row in existing_items:
        if str(row.get('item_name') or '') == item_name:
            try:
                current_qty = int(row.get('quantity') or 0)
            except (TypeError, ValueError):
                current_qty = 0
            break

    if current_qty < quantity:
        return jsonify({"error": f'Not enough item quantity to sell. Available {current_qty}.'}), 400

    remaining_qty = current_qty - quantity
    if remaining_qty > 0:
        upsert_inventory_item(user_id, item_name, remaining_qty, target_inventory_table, guild_id=selected_guild_id)
    else:
        delete_inventory_item(user_id, item_name, target_inventory_table, guild_id=selected_guild_id)

    total_return = float(price * quantity)
    current_currency = fetch_currency_amount(user_id, target_table, guild_id=selected_guild_id)
    new_currency = current_currency + total_return
    set_currency_amount(user_id, new_currency, target_table, guild_id=selected_guild_id)

    return jsonify(
        {
            'status': 'success',
            'message': f'Sold {quantity} x {item_name} for {total_return:.2f}.',
            'currency': new_currency,
            'item_name': item_name,
            'quantity_sold': quantity,
            'total_return': total_return,
            'sheet_id': sheet_id or None,
            'scope': 'account' if use_account_scope else 'sheet',
            'sheet_currency': new_currency,
        }
    )


@app.route('/api/shop', methods=['GET'])
def get_shop():
    """Get all shop items"""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        conn = get_db_connection(SHOP_DB)
        c = conn.cursor()
        c.execute('SELECT item_name, price FROM shop WHERE guild_id=? ORDER BY item_name', (selected_guild_id,))
        items = c.fetchall()
        conn.close()
        return jsonify(items)
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

@app.route('/api/shop', methods=['POST'])
def add_shop_item():
    """Add shop item"""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        data = request.json
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        item_name = validate_admin_name(data.get('item_name', ''), 'Item name', 120)
        price = data.get('price', 0)

        if not item_name:
            return jsonify({"error": "Item name required"}), 400
        if price < 0:
            return jsonify({"error": "Price cannot be negative"}), 400

        conn = get_db_connection(SHOP_DB)
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO shop (guild_id, item_name, price) VALUES (?, ?, ?)', (selected_guild_id, item_name, price))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

@app.route('/api/shop/<item_name>', methods=['DELETE'])
def delete_shop_item(item_name):
    """Delete shop item"""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        item_name = validate_admin_name(item_name, 'Item name', 120)
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        conn = get_db_connection(SHOP_DB)
        c = conn.cursor()
        c.execute('DELETE FROM shop WHERE guild_id=? AND item_name=?', (selected_guild_id, item_name))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return api_error_response('Request failed.', 400, e)


@app.route('/api/shop', methods=['DELETE'])
def reset_shop():
    """Remove all shop entries."""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        conn = get_db_connection(SHOP_DB)
        c = conn.cursor()
        c.execute('DELETE FROM shop WHERE guild_id=?', (selected_guild_id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

# --- Jobs Management ---
@app.route('/api/jobs', methods=['GET'])
def get_jobs():
    """Get all jobs"""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        if not os.path.exists(ECONOMY_DB):
            return jsonify([])

        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)

        conn = get_db_connection(ECONOMY_DB)
        c = conn.cursor()
        c.execute('SELECT job_name, payment FROM jobs WHERE guild_id=? ORDER BY job_name', (selected_guild_id,))
        jobs = c.fetchall()
        conn.close()
        return jsonify(jobs)
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

@app.route('/api/jobs', methods=['POST'])
def add_job():
    """Add job"""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        data = request.json
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        job_name = validate_admin_name(data.get('job_name', ''), 'Job name', 120)
        payment = float(data.get('payment', 0))

        if not job_name:
            return jsonify({"error": "Job name required"}), 400
        if payment < 0:
            return jsonify({"error": "Payment cannot be negative"}), 400

        os.makedirs(os.path.dirname(ECONOMY_DB), exist_ok=True)
        conn = get_db_connection(ECONOMY_DB)
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO jobs (guild_id, job_name, payment) VALUES (?, ?, ?)', (selected_guild_id, job_name, payment))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except ValueError:
        return jsonify({"error": "Payment must be a number"}), 400
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

@app.route('/api/jobs/<job_name>', methods=['DELETE'])
def delete_job(job_name):
    """Delete job"""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        job_name = validate_admin_name(job_name, 'Job name', 120)
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        conn = get_db_connection(ECONOMY_DB)
        c = conn.cursor()
        c.execute('DELETE FROM jobs WHERE guild_id=? AND job_name=?', (selected_guild_id, job_name))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return api_error_response('Request failed.', 400, e)


@app.route('/api/jobs', methods=['DELETE'])
def reset_jobs():
    """Remove all job entries."""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        os.makedirs(os.path.dirname(ECONOMY_DB), exist_ok=True)
        conn = get_db_connection(ECONOMY_DB)
        c = conn.cursor()
        c.execute('DELETE FROM jobs WHERE guild_id=?', (selected_guild_id,))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

# --- Work Cooldown ---
@app.route('/api/settings/work-cooldown', methods=['GET'])
def get_work_cooldown():
    """Get work cooldown setting"""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        conn = get_db_connection(SETTINGS_DB)
        c = conn.cursor()
        c.execute('SELECT days FROM WorkCooldown WHERE guild_id=?', (selected_guild_id,))
        row = c.fetchone()
        conn.close()
        return jsonify({"days": row['days'] if row else 0})
    except Exception as e:
        return jsonify({"days": 0})  # Return default instead of error

@app.route('/api/settings/work-cooldown', methods=['POST'])
def set_work_cooldown():
    """Set work cooldown"""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        data = request.json
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        days = int(data.get('days', 0))

        if days < 0:
            return jsonify({"error": "Days cannot be negative"}), 400

        conn = get_db_connection(SETTINGS_DB)
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO WorkCooldown (guild_id, days) VALUES (?, ?)', (selected_guild_id, days))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except ValueError:
        return jsonify({"error": "Days must be a number"}), 400
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

# --- Death Cooldown ---
@app.route('/api/settings/death-cooldown', methods=['GET'])
def get_death_cooldown():
    """Get death cooldown setting"""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        if not os.path.exists(DEATHCOOLDOWN_DB):
            return jsonify({"days": 0, "infinite": False})

        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)

        conn = get_db_connection(DEATHCOOLDOWN_DB)
        c = conn.cursor()
        c.execute('SELECT cooldown, infinite FROM GlobalSettings WHERE guild_id=?', (selected_guild_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            return jsonify({"days": 0, "infinite": False})
        return jsonify({
            "days": row.get('cooldown', 0) or 0,
            "infinite": bool(row.get('infinite', 0) or 0)
        })
    except Exception as e:
        return jsonify({"days": 0, "infinite": False})  # Return default instead of error

@app.route('/api/settings/death-cooldown', methods=['POST'])
def set_death_cooldown():
    """Set death cooldown"""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        data = request.json
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        days = int(data.get('days', 0))
        infinite_raw = data.get('infinite', None)

        if days < 0:
            return jsonify({"error": "Days cannot be negative"}), 400

        os.makedirs(os.path.dirname(DEATHCOOLDOWN_DB), exist_ok=True)
        conn = get_db_connection(DEATHCOOLDOWN_DB)
        c = conn.cursor()
        if infinite_raw is None:
            c.execute('SELECT infinite FROM GlobalSettings WHERE guild_id=?', (selected_guild_id,))
            row = c.fetchone()
            infinite_val = int(row['infinite']) if row else 0
        else:
            infinite_val = 1 if bool(infinite_raw) else 0

        c.execute(
            '''INSERT OR REPLACE INTO GlobalSettings (guild_id, cooldown, infinite)
               VALUES (?, ?, ?)''',
            (selected_guild_id, days, infinite_val)
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except ValueError:
        return jsonify({"error": "Days must be a number"}), 400
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

# --- Combat Rules ---
@app.route('/api/settings/combat-rules', methods=['GET'])
def get_combat_rules():
    """Get fight dynamic combat rule weights"""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        if not os.path.exists(COMBAT_DB):
            return jsonify({
                "solid_hit": 0.25,
                "small_hit": 0.25,
                "miss": 0.25,
                "self_hit": 0.25,
            })

        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)

        conn = get_db_connection(COMBAT_DB)
        c = conn.cursor()
        c.execute(
            'SELECT hitchance, missed1, missed2, missed3 FROM Rules WHERE guild_id=? ORDER BY id DESC LIMIT 1',
            (selected_guild_id,),
        )
        row = c.fetchone()
        conn.close()

        if not row:
            return jsonify({
                "solid_hit": 0.25,
                "small_hit": 0.25,
                "miss": 0.25,
                "self_hit": 0.25,
            })

        return jsonify({
            "solid_hit": row.get('hitchance', 0.25),
            "small_hit": row.get('missed1', 0.25),
            "miss": row.get('missed2', 0.25),
            "self_hit": row.get('missed3', 0.25),
        })
    except Exception:
        return jsonify({
            "solid_hit": 0.25,
            "small_hit": 0.25,
            "miss": 0.25,
            "self_hit": 0.25,
        })

@app.route('/api/settings/combat-rules', methods=['POST'])
def set_combat_rules():
    """Set fight dynamic combat rule weights"""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        data = request.json
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        solid_hit = float(data.get('solid_hit', 0.25))
        small_hit = float(data.get('small_hit', 0.25))
        miss = float(data.get('miss', 0.25))
        self_hit = float(data.get('self_hit', 0.25))

        values = [solid_hit, small_hit, miss, self_hit]
        if any(v < 0 for v in values):
            return jsonify({"error": "Combat rule weights cannot be negative"}), 400

        total = sum(values)
        if abs(total - 1.0) > 0.0001:
            return jsonify({"error": "Combat rule weights must sum to 1.0"}), 400

        os.makedirs(os.path.dirname(COMBAT_DB), exist_ok=True)
        conn = get_db_connection(COMBAT_DB)
        c = conn.cursor()
        c.execute(
            'INSERT INTO Rules (guild_id, hitchance, missed1, missed2, missed3) VALUES (?, ?, ?, ?, ?)',
            (selected_guild_id, solid_hit, small_hit, miss, self_hit)
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except ValueError:
        return jsonify({"error": "Combat rule weights must be numbers"}), 400
    except Exception as e:
        return api_error_response('Request failed.', 400, e)


@app.route('/api/settings/reset', methods=['POST'])
def reset_settings():
    """Reset settings values to dashboard defaults."""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        conn = get_db_connection(SETTINGS_DB)
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO WorkCooldown (guild_id, days) VALUES (?, 0)', (selected_guild_id,))
        conn.commit()
        conn.close()

        os.makedirs(os.path.dirname(DEATHCOOLDOWN_DB), exist_ok=True)
        conn = get_db_connection(DEATHCOOLDOWN_DB)
        c = conn.cursor()
        c.execute(
            'INSERT OR REPLACE INTO GlobalSettings (guild_id, cooldown, infinite) VALUES (?, 0, 0)',
            (selected_guild_id,),
        )
        conn.commit()
        conn.close()

        os.makedirs(os.path.dirname(COMBAT_DB), exist_ok=True)
        conn = get_db_connection(COMBAT_DB)
        c = conn.cursor()
        c.execute('DELETE FROM Rules WHERE guild_id=?', (selected_guild_id,))
        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "defaults": {
                "work_cooldown_days": 0,
                "death_cooldown_days": 0,
                "death_infinite": False,
                "combat_rules": {
                    "solid_hit": 0.25,
                    "small_hit": 0.25,
                    "miss": 0.25,
                    "self_hit": 0.25
                }
            }
        })
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

# --- Items Management ---
@app.route('/api/items', methods=['GET'])
def get_items():
    """Get all items"""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        if not os.path.exists(ITEMS_DB):
            return jsonify([])

        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)

        conn = get_db_connection(ITEMS_DB)
        c = conn.cursor()
        c.execute(
            'SELECT name, consumable, image, description FROM items WHERE guild_id=? ORDER BY name',
            (selected_guild_id,),
        )
        items = c.fetchall()
        conn.close()
        return jsonify(items)
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

@app.route('/api/items', methods=['POST'])
def add_item():
    """Add item"""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        data = request.json
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        name = validate_admin_name(data.get('name', ''), 'Item name', 120)
        consumable = data.get('consumable', 'No')
        description = data.get('description', '').strip()

        if not name:
            return jsonify({"error": "Item name required"}), 400
        if consumable not in ('Yes', 'No'):
            return jsonify({"error": "Consumable must be Yes or No"}), 400

        os.makedirs(os.path.dirname(ITEMS_DB), exist_ok=True)
        conn = get_db_connection(ITEMS_DB)
        c = conn.cursor()
        c.execute(
            '''INSERT OR REPLACE INTO items (guild_id, name, consumable, description)
               VALUES (?, ?, ?, ?)''',
            (selected_guild_id, name, consumable, description),
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Item name already exists"}), 400
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

@app.route('/api/items/<item_name>/image', methods=['POST'])
def upload_item_image(item_name):
    """Upload image for item"""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        item_name = validate_admin_name(item_name, 'Item name', 120)
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400

        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)

        file = request.files['file']
        ext = validate_item_image_upload(file)

        # Generate unique filename
        import uuid
        image_id = f"{uuid.uuid4().hex}.{ext}"

        # Ensure directory exists and use proper path
        images_dir = str(ITEMS_DIR)
        os.makedirs(images_dir, exist_ok=True)
        image_path = os.path.join(images_dir, image_id)

        file.save(image_path)

        # Update database
        conn = get_db_connection(ITEMS_DB)
        c = conn.cursor()
        c.execute('SELECT image FROM items WHERE guild_id=? AND name=?', (selected_guild_id, item_name))
        row = c.fetchone()
        old_image = str((row or {}).get('image') or '').strip()
        c.execute('UPDATE items SET image=? WHERE guild_id=? AND name=?', (image_id, selected_guild_id, item_name))
        conn.commit()
        conn.close()

        if old_image and old_image != image_id:
            delete_item_image_if_unreferenced(old_image)

        return jsonify({"status": "success", "image_id": image_id})
    except ValueError as e:
        return api_error_response('Invalid request data.', 400, e)
    except Exception as e:
        return api_error_response('Failed to upload image', 400, e)

@app.route('/api/items/<item_name>/image', methods=['GET'])
def get_item_image(item_name):
    """Get item image"""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        item_name = validate_admin_name(item_name, 'Item name', 120)
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        conn = get_db_connection(ITEMS_DB)
        c = conn.cursor()
        c.execute('SELECT image FROM items WHERE guild_id=? AND name=?', (selected_guild_id, item_name))
        row = c.fetchone()
        conn.close()

        if not row or not row.get('image'):
            return jsonify({"error": "No image for item"}), 404

        images_dir = str(ITEMS_DIR)
        image_path = os.path.join(images_dir, row['image'])
        if not os.path.exists(image_path):
            return jsonify({"error": "Image not found"}), 404

        return send_file(image_path)
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

@app.route('/api/items/<item_name>', methods=['DELETE'])
def delete_item(item_name):
    """Delete item and its image"""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        item_name = validate_admin_name(item_name, 'Item name', 120)
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        conn = get_db_connection(ITEMS_DB)
        c = conn.cursor()
        c.execute('SELECT image FROM items WHERE guild_id=? AND name=?', (selected_guild_id, item_name))
        row = c.fetchone()
        old_image = str((row or {}).get('image') or '').strip()

        c.execute('DELETE FROM items WHERE guild_id=? AND name=?', (selected_guild_id, item_name))
        conn.commit()
        conn.close()

        if old_image:
            delete_item_image_if_unreferenced(old_image)
        return jsonify({"status": "success"})
    except Exception as e:
        return api_error_response('Request failed.', 400, e)


@app.route('/api/items', methods=['DELETE'])
def reset_items():
    """Remove all item entries and their uploaded images."""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        selected_guild_id = get_selected_server_id_required()
        ensure_server_scoped_dashboard_schema(selected_guild_id)
        image_names = []
        if os.path.exists(ITEMS_DB):
            conn = get_db_connection(ITEMS_DB)
            c = conn.cursor()
            c.execute('SELECT image FROM items WHERE guild_id=? AND image IS NOT NULL AND image != ""', (selected_guild_id,))
            image_names = [row['image'] for row in c.fetchall() if row.get('image')]
            c.execute('DELETE FROM items WHERE guild_id=?', (selected_guild_id,))
            conn.commit()
            conn.close()

        for image_name in image_names:
            delete_item_image_if_unreferenced(image_name)

        return jsonify({"status": "success"})
    except Exception as e:
        return api_error_response('Request failed.', 400, e)


@app.route('/api/audit-logs', methods=['GET'])
def get_audit_logs():
    """Return recent dashboard audit log entries."""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        limit_raw = request.args.get('limit', '50')
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 50
        limit = max(1, min(limit, 500))

        free_text = str(request.args.get('q', '') or '').strip().lower()
        actor_filter = str(request.args.get('actor', '') or '').strip().lower()
        where_filter = str(request.args.get('where', '') or '').strip().lower()
        source_filter = str(request.args.get('source', '') or '').strip().lower()

        purge_old_audit_logs()
        conn = get_db_connection(AUDIT_DB)
        c = conn.cursor()
        c.execute(
            '''SELECT id, created_at, actor, source, method, route, action, request_details, response_status
               FROM AuditLog
               WHERE (? = '' OR LOWER(actor) LIKE ?)
                 AND (? = '' OR LOWER(route) LIKE ?)
                 AND (? = '' OR LOWER(source) = ?)
                 AND (
                    ? = ''
                    OR LOWER(actor) LIKE ?
                    OR LOWER(source) LIKE ?
                    OR LOWER(route) LIKE ?
                    OR LOWER(method) LIKE ?
                    OR LOWER(action) LIKE ?
                    OR LOWER(COALESCE(request_details, '')) LIKE ?
                 )
               ORDER BY id DESC
               LIMIT ?''',
            (
                actor_filter, f'%{actor_filter}%',
                where_filter, f'%{where_filter}%',
                source_filter, source_filter,
                free_text,
                f'%{free_text}%',
                f'%{free_text}%',
                f'%{free_text}%',
                f'%{free_text}%',
                f'%{free_text}%',
                f'%{free_text}%',
                limit,
            )
        )
        rows = c.fetchall() or []
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

# --- Database Info ---
@app.route('/api/info', methods=['GET'])
def get_info():
    """Get bot database info"""
    if role_is_member():
        return jsonify({"error": "This section is hidden for Member role mode."}), 403
    try:
        configured_servers = []
        if os.path.exists(SETTINGS_DB):
            conn = get_db_connection(SETTINGS_DB)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS Server (
                guild_id INTEGER PRIMARY KEY,
                admin_role_id INTEGER,
                admin_channel_id INTEGER,
                member_role_id INTEGER,
                member_channel_id INTEGER
            )''')
            c.execute('SELECT guild_id FROM Server')
            configured_servers = c.fetchall() or []
            conn.close()

        info = {
            "bot_dir": str(BOT_DIR),
            "databases": {
                "settings": os.path.exists(SETTINGS_DB),
                "sheets": os.path.exists(SHEETS_DB),
                "audit": os.path.exists(AUDIT_DB),
                "shop": os.path.exists(SHOP_DB),
                "economy": os.path.exists(ECONOMY_DB),
                "inventory": os.path.exists(INVENTORY_DB),
                "items": os.path.exists(ITEMS_DB),
                "combat": os.path.exists(COMBAT_DB),
            },
            "live_server_count": get_live_bot_guild_count(),
            "configured_server_count": len(configured_servers),
            "timestamp": datetime.now().isoformat()
        }
        return jsonify(info)
    except Exception as e:
        return api_error_response('Request failed.', 400, e)

if __name__ == '__main__':
    bind_host = get_user_server_bind_host()
    bind_port = get_user_server_port()
    debug_enabled = get_user_server_bool_setting('FLASK_DEBUG', False)
    public_base_url = get_public_base_url()
    secure_public_url = is_secure_public_url()
    ssl_context = get_ssl_context_config()
    trust_proxy_headers = get_user_server_bool_setting('TRUST_PROXY_HEADERS', False)

    # Keep runtime logs focused on errors to avoid noisy request streams.
    app.logger.setLevel(logging.ERROR)
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    logging.getLogger('urllib3').setLevel(logging.ERROR)

    print("=" * 60)
    print("DND Flow - Offline Backup Web Server")
    print("=" * 60)
    print(f"\n[OK] Starting on {public_base_url}")
    print(f"[OK] Listening on {bind_host}:{bind_port}")
    print("[OK] Discord login is disabled in offline mode\n")

    if ssl_context:
        print(f"[OK] TLS enabled with certificate: {get_ssl_cert_file()}")
    elif secure_public_url and trust_proxy_headers:
        print("[OK] HTTPS expected via reverse proxy (TRUST_PROXY_HEADERS=True)")
    elif secure_public_url:
        print("! HTTPS is configured in PUBLIC_BASE_URL / DISCORD_REDIRECT_URI")
        print("! but Flask is still serving plain HTTP on this port.")
        print("! Configure ONLINE_WEB_SERVER_SSL_CERT and ONLINE_WEB_SERVER_SSL_KEY, or terminate TLS in a reverse proxy.\n")

    app.jinja_env.cache = {}  # Clear template cache
    app.run(host=bind_host, port=bind_port, debug=debug_enabled, ssl_context=ssl_context)





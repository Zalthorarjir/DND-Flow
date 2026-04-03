"""Shared audit logging utilities for Discord bot interactions."""

import json
import os
import sqlite3
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
SETTINGS_DB = os.path.join(BASE_DIR, 'databases', 'Settings.db')
AUDIT_DB = os.path.join(BASE_DIR, 'databases', 'Audit.db')


def _json_dump_limited(value, max_len=1500):
    """Serialize JSON payload while keeping rows compact."""
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        raw = str(value)
    return raw[:max_len]


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
    if not os.path.exists(SETTINGS_DB):
        return

    legacy_conn = sqlite3.connect(SETTINGS_DB)
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

    audit_conn = sqlite3.connect(AUDIT_DB)
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

    cleanup_conn = sqlite3.connect(SETTINGS_DB)
    try:
        cleanup_conn.execute('DROP TABLE IF EXISTS AuditLog')
        cleanup_conn.commit()
    finally:
        cleanup_conn.close()


def ensure_audit_log_table():
    """Create audit log table if missing."""
    conn = sqlite3.connect(AUDIT_DB)
    try:
        _create_audit_log_schema(conn)
        conn.commit()
    finally:
        conn.close()
    _migrate_legacy_audit_log()


def purge_old_audit_logs():
    """Delete audit records older than 30 days."""
    ensure_audit_log_table()
    cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat(timespec='seconds') + 'Z'
    conn = sqlite3.connect(AUDIT_DB)
    try:
        conn.execute('DELETE FROM AuditLog WHERE created_at < ?', (cutoff,))
        conn.commit()
    finally:
        conn.close()


def write_discord_audit_log(actor, route, action, request_details=None, response_status=200):
    """Persist a Discord interaction audit entry."""
    purge_old_audit_logs()
    conn = sqlite3.connect(AUDIT_DB)
    try:
        conn.execute(
            '''INSERT INTO AuditLog (
                created_at, actor, source, method, route, action, request_details, response_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                datetime.utcnow().isoformat(timespec='seconds') + 'Z',
                str(actor or 'Unknown'),
                'discord_bot',
                'DISCORD',
                str(route or ''),
                str(action or 'discord_command'),
                _json_dump_limited(request_details),
                int(response_status or 0),
            )
        )
        conn.commit()
    finally:
        conn.close()


def _flatten_option_pairs(options, prefix=''):
    """Return flat list of (name, value) from nested slash command options."""
    pairs = []
    for opt in options or []:
        name = str(opt.get('name', '') or '').strip()
        option_path = ' '.join(part for part in (prefix, name) if part).strip()
        if 'value' in opt:
            pairs.append((option_path or name or 'value', opt.get('value')))
            continue
        child_options = opt.get('options') or []
        pairs.extend(_flatten_option_pairs(child_options, option_path))
    return pairs


def _build_full_command(command_name, options):
    """Build human-readable slash command invocation string."""
    base = f"/{command_name}" if command_name else '/unknown'
    parts = []
    for name, value in _flatten_option_pairs(options):
        if not name:
            continue
        parts.append(f"{name}:{value}")
    return f"{base} {' '.join(parts)}".strip()


def _build_input_data(options):
    """Build readable field/value input data for audit display."""
    input_data = {}
    for name, value in _flatten_option_pairs(options):
        field_name = str(name or 'value').strip() or 'value'
        if field_name in input_data:
            current = input_data[field_name]
            if isinstance(current, list):
                current.append(value)
            else:
                input_data[field_name] = [current, value]
        else:
            input_data[field_name] = value
    return input_data or None


def build_discord_interaction_details(interaction, command_name=None):
    """Build a compact payload for audit rows from a Discord interaction."""
    data = getattr(interaction, 'data', {}) or {}
    options = data.get('options', []) if isinstance(data, dict) else []
    channel_obj = getattr(interaction, 'channel', None)
    channel_name = None
    if channel_obj is not None:
        channel_name = getattr(channel_obj, 'name', None) or str(channel_obj)

    resolved_command_name = command_name or data.get('name') or 'unknown'

    return {
        'guild_id': str(interaction.guild_id) if getattr(interaction, 'guild_id', None) else None,
        'channel_id': str(interaction.channel_id) if getattr(interaction, 'channel_id', None) else None,
        'channel_name': channel_name,
        'user_id': str(getattr(getattr(interaction, 'user', None), 'id', None) or ''),
        'command': resolved_command_name,
        'full_command': _build_full_command(resolved_command_name, options),
        'input_data': _build_input_data(options),
        'options': options,
    }

# Slash Command Registration Guide

This guide explains how command registration works in the bot and how to troubleshoot missing slash commands.

## How Sync Works

When `Discord_Bot/main.py` boots, loaded cogs register their app commands and the bot syncs the command tree with Discord.

Global sync can take time to propagate. Guild-targeted sync appears faster for testing.

## Standard Startup Procedure

1. Start the bot from `Discord_Bot/`:

```bash
python main.py
```

2. Confirm extension loading output is healthy.
3. Confirm command sync output reports non-zero synced commands.

If extensions fail to load, their commands will not sync.

## Expected Command Coverage

Core groups/flows should include:

- `/config`
- `/sheet`
- `/inventory`
- `/currency`
- `/work`
- `/job`
- `/item`
- `/shop`
- `/give_money`
- `/give_item`
- `/fight_dynamic`
- `/health_track`
- `/death`
- `/search`
- `/help`

Exact command set depends on currently loaded cogs in `Discord_Bot/commands/`.

## Most Common Causes of Missing Commands

1. Bot restarted before sync completed.
2. Bot invite missing `applications.commands` scope.
3. Extension import/load error prevented command registration.
4. Discord propagation delay for global commands.
5. Logged into wrong guild/user context in Discord client.

## Fast Troubleshooting Checklist

1. Restart bot and wait until sync log line appears.
2. Review console for tracebacks during extension loading.
3. Verify Discord application scopes and bot permissions.
4. Confirm test user has permission to view/use commands.
5. Test in a single known guild before relying on global rollout.

## Optional: Temporary Guild-Only Sync

For rapid iteration, temporarily sync to one guild:

```python
guild = discord.Object(id=YOUR_GUILD_ID)
bot.tree.copy_global_to(guild=guild)
synced = await bot.tree.sync(guild=guild)
print(f"Synced {len(synced)} commands to guild {YOUR_GUILD_ID}")
```

Remove this temporary block after testing so production uses your normal sync approach.

## Related Docs

- `docs/README.md`
- `docs/FILE_REFERENCE.md`

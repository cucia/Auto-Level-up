# Discord Leveling Automation

A minimal, user-focused Discord bot for automating XP farming in leveling systems. Supports text and voice activities with anti-detection features.

## Features

- **Text Farming**: Sends random motivational messages to specified channels at configurable intervals, with optional auto-deletion.
- **Voice Farming**: Joins empty voice channels, farms for set hours, instantly leaves if someone joins, then rotates.
- **User Token Support**: Uses `discord.py-self` for seamless user account automation (no bot required).
- **Minimal & Self-Contained**: 3 Python files + configs. No external dependencies beyond essentials.
- **Anti-Detection**: Jittered timing, random selections, and instant exits to mimic human behavior.
- **Docker Support**: Containerized with health checks (optional).

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure
- Copy `.env.example` to `.env`.
- Add your **Discord user token** (get from browser dev tools: Login → Network → Refresh → Find `/api/users/@me` → Copy `Authorization` header).
- Set `TARGET_CHANNELS` and `TARGET_VCS` to comma-separated IDs of channels/VCs you own/manage.
- Adjust intervals and modes as needed.

### 3. Run
```bash
python main.py
```

For Docker:
```bash
docker-compose up --build
```

## Configuration (.env)

| Variable | Description | Default |
|----------|-------------|---------|
| `DISCORD_TOKEN` | Your Discord user token | Required |
| `LEVELING_MODE` | `text`, `voice`, or `both` | `both` |
| `TEXT_INTERVAL_SEC` | Seconds between messages | `100` |
| `TEXT_JITTER_SEC` | Random jitter in seconds | `0` |
| `TEXT_DELETE_ENABLED` | Auto-delete messages? (`true`/`false`) | `true` |
| `TEXT_AUTO_DELETE_SEC` | Delete delay in seconds | `3` |
| `TARGET_CHANNELS` | Comma-separated channel IDs | Required for text |
| `VOICE_ROTATION_HOURS` | Hours to farm per VC | `1` |
| `TARGET_VCS` | Comma-separated VC IDs | Required for voice |
| `LOG_LEVEL` | Logging level (`INFO`, `DEBUG`, etc.) | `INFO` |

## How It Works

- **Text Module**: Loads quotes from `greetings.txt`, sends to channels, deletes if enabled.
- **Voice Module**: Scans VCs for emptiness, joins, monitors for joins, rotates after time.
- **Safety**: Only interacts with specified channels/VCs. Respects Discord TOS (use at your own risk).

## Project Structure

- `main.py`: Core logic, auth, gateway, and orchestration.
- `text_module.py`: Text farming implementation.
- `voice_module.py`: Voice farming implementation.
- `greetings.txt`: Message pool (editable).
- `.env`: Configuration (copy from `.env.example`).

## Requirements

- Python 3.11+
- `discord.py-self` (for user tokens)
- Other deps in `requirements.txt`

## Notes

- **User Tokens Only**: Bot tokens won't work (use `discord.py` for bots).
- **Permissions**: Ensure your account can send messages and join VCs in target channels.
- **TOS Warning**: Automation may violate Discord's terms. Use responsibly.
- **Troubleshooting**: Check logs for errors. Voice may have connection issues—retries are built-in.

## License

MIT - Do what you want, but don't blame me.

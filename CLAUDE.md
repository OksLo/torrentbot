# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

Three-service self-hosted media stack:

1. **Telegram bot** (`bot/`) — accepts magnet links and `.torrent` files from users, forwards them to qBittorrent
2. **qBittorrent** — downloads torrents into `./downloads/`
3. **Samba + Jellyfin** — serve `./downloads/` to PCs (SMB) and TVs (Jellyfin/DLNA)

All services run via Docker Compose.

## Commands

```bash
make up            # start all services detached
make down          # stop all services
make logs          # tail all logs
make bot-logs      # tail bot logs only
make restart-bot   # restart the bot container
```

First-time setup:
```bash
cp .env.example .env   # fill in BOT_TOKEN and QBIT_PASSWORD
make up
```

qBittorrent Web UI is at `http://localhost:8080`. Jellyfin is at `http://localhost:8096`.

## Setup Service

The `setup` service is published to GitHub Container Registry as `ghcr.io/okslo/torrentbot-setup:latest`. On first boot, it:

1. Connects to qBittorrent and Jellyfin (waits for healthchecks)
2. Sets the qBittorrent Web UI password
3. Completes the Jellyfin wizard and creates the admin account
4. Adds a Downloads library pointing to `/media`
5. Configures qBittorrent autorun to refresh Jellyfin on torrent completion
6. Writes a sentinel file (`/config/.setup_done`) to skip on future starts

## Architecture

```
bot/
  main.py              # bot entry point, wires routers
  config.py            # pydantic-settings; reads from env
  handlers/
    torrent.py         # handles magnet: text and .torrent file uploads
    status.py          # /status and /help commands
  services/
    qbittorrent.py     # async httpx client for qBittorrent Web API v2

setup/
  Dockerfile           # containerizes setup.py for GHCR publication
  setup.py             # first-run configuration script (idempotent)
```

The bot is stateless — it holds no download state itself, everything lives in qBittorrent. `QBittorrentClient` in `services/qbittorrent.py` is a module-level singleton that lazily authenticates on first use.

## Environment Variables

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token from @BotFather |
| `QBIT_USERNAME` | qBittorrent Web UI username (default: `admin`) |
| `QBIT_PASSWORD` | qBittorrent Web UI password |
| `TZ` | Timezone (default: `Europe/London`) |

## Runtime Volumes

Docker creates these at startup — they are gitignored:

- `./downloads/` — shared download directory (Samba + Jellyfin serve this)
- `./config/qbittorrent/` — qBittorrent config persistence
- `./config/jellyfin/` — Jellyfin config persistence

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Maintenance Rule

On every code change, update the relevant sections of `README.md` and `CLAUDE.md` to reflect the new state of the project.

## What This Project Does

Five-service self-hosted media stack:

1. **Telegram bot** (`bot/`) — AI assistant powered by Google Gemini. Accepts natural language commands, magnet links, and `.torrent` files. Uses MCP tools to control qBittorrent and Jellyfin.
2. **qBittorrent** — downloads torrents into `./downloads/`
3. **Jellyfin** — media streaming server; optionally uses Intel GPU hardware transcoding via VA-API
4. **Samba** — serves `./downloads/` over SMB to PCs
5. **Setup** — one-time first-boot configuration service

All services run via Docker Compose. GPU passthrough is auto-detected at `make up` time.

## Commands

```bash
make up            # start all services (auto-detects Intel GPU)
make down          # stop all services
make logs          # tail all logs
make bot-logs      # tail bot logs only
make restart-bot   # restart the bot container
make upgrade       # pull latest images and recreate all services
```

First-time setup:
```bash
cp .env.example .env   # fill in required variables
make up
```

qBittorrent Web UI is at `http://localhost:8080`. Jellyfin is at `http://localhost:8096`.

## GPU Support

If `/dev/dri` exists on the host, `make up` automatically appends `-f docker-compose.gpu.yml`, which:

- Passes `/dev/dri` into the Jellyfin container
- Adds the host `render` and `video` group IDs (resolved via `getent`) to the container
- Sets `JELLYFIN_HW_ACCEL=vaapi` for the setup container, enabling VA-API in Jellyfin's encoding config

No manual configuration needed. On hosts without `/dev/dri` the stack runs without GPU support.

## Setup Service

The `setup` service is published to GitHub Container Registry as `ghcr.io/okslo/torrentbot-setup:latest`. On first boot, it:

1. Connects to qBittorrent and Jellyfin (waits for healthchecks)
2. Sets the qBittorrent Web UI password
3. Completes the Jellyfin wizard and creates the admin account
4. Adds a Downloads library pointing to `/media`
5. Configures qBittorrent autorun to refresh Jellyfin on torrent completion
6. Creates a `TorrentBot` Jellyfin API key and writes it to `/config/jellyfin.env`
7. Configures VA-API hardware transcoding if `JELLYFIN_HW_ACCEL=vaapi` is set

The script is idempotent — it verifies and reapplies configuration on every container start.

## Architecture

```
bot/
  main.py              # entry point: MCP sessions, Gemini client, reconnect loop
  config.py            # pydantic-settings; reads from env
  smoke_test.py        # import-level smoke test run at container build
  handlers/
    ai.py              # all message handling: Gemini AI loop, tool dispatch, history
  services/
    qbittorrent.py     # async httpx client for qBittorrent Web API v2
    history.py         # SQLite-backed per-chat conversation history

setup/
  Dockerfile           # containerizes setup.py for GHCR publication
  setup.py             # first-run configuration script (idempotent)

docker-compose.yml     # base service definitions
docker-compose.gpu.yml # GPU overlay: /dev/dri passthrough + VA-API config
Makefile               # make targets; auto-detects GPU and applies overlay
```

### Bot internals

- `main.py` opens two persistent MCP sessions (SSE for qBittorrent, streamable HTTP for Jellyfin) and exposes their tools to the AI handler. On transport errors it tears down sessions and reconnects with 5-second backoff.
- `ai.py` runs a Gemini `generate_content` loop per message, executing MCP tool calls until the model returns a final text response. Conversation history is persisted to SQLite and loaded on first message per chat.
- Model fallback: `GEMINI_MODEL` accepts a comma-separated list in priority order. Rate-limited models (429 / RESOURCE_EXHAUSTED) are skipped in-process for 8 hours.
- All Telegram replies go through `_safe_reply` to prevent `TelegramNetworkError` from crashing the handler.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | yes | Telegram bot token from @BotFather |
| `QBIT_PASSWORD` | yes | qBittorrent Web UI password |
| `GEMINI_API_KEY` | yes | Google Gemini API key |
| `MCP_HTTP_TOKEN` | yes | Bearer token for Jellyfin MCP HTTP endpoint |
| `JELLYFIN_PASSWORD` | yes | Jellyfin admin password |
| `QBIT_USERNAME` | no | qBittorrent username (default: `admin`) |
| `JELLYFIN_USERNAME` | no | Jellyfin admin username (default: `admin`) |
| `GEMINI_MODEL` | no | Comma-separated model list, priority order (default: `gemini-2.5-flash`) |
| `QBIT_MCP_URL` | no | qBittorrent MCP SSE URL (default: `http://qbittorrent-mcp:3000/sse`) |
| `JELLYFIN_MCP_URL` | no | Jellyfin MCP URL (default: `http://jellyfin-mcp:8080/mcp`) |
| `TZ` | no | Timezone (default: `Europe/London`) |

## Runtime Volumes

Docker creates these at startup — they are gitignored:

- `./downloads/` — shared download directory (Samba + Jellyfin serve this)
- `./data/` — bot runtime data: `history.db` (per-chat conversation history)
- `./config/qbittorrent/` — qBittorrent config persistence
- `./config/jellyfin/` — Jellyfin config persistence; `jellyfin.env` holds the Jellyfin API key

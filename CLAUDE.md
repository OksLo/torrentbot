# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Maintenance Rule

On every code change, update the relevant sections of `README.md` and `CLAUDE.md` to reflect the new state of the project.

## What This Project Does

Five-service self-hosted media stack:

1. **Telegram bot** (`bot/`) — AI assistant powered by Google Gemini. Accepts natural language commands, magnet links, and `.torrent` files. Uses MCP tools to control qBittorrent and Jellyfin.
2. **qBittorrent** — downloads torrents into `./downloads/`
3. **Jellyfin** — media streaming server; optionally uses Intel GPU hardware transcoding via VA-API
4. **Samba** — serves `./downloads/` over SMB to PCs. Its `-p` flag recursively chowns the share to `smbuser` on every start; `USERID`/`GROUPID=1000` keep that in sync with qBittorrent's `PUID`/`PGID` (the image default is 100:101)
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
  main.py              # entry point: aiogram dispatcher, Telegram handlers, .torrent upload
  assistant.py         # Gemini: system prompt, keyword routing, MCP sessions, model fallback + retry
  history.py           # SQLite-backed per-chat conversation history
  config.py            # pydantic-settings; reads from env

setup/
  Dockerfile           # containerizes setup.py for GHCR publication
  setup.py             # first-run configuration script (idempotent)

docker-compose.yml     # base service definitions
docker-compose.gpu.yml # GPU overlay: /dev/dri passthrough + VA-API config
docker-compose.blkio.yml # Optional blkio override to limit qBittorrent drive I/O
Makefile               # make targets; auto-detects GPU and applies overlay
```

### Bot internals

- Keep the code small and lean on libraries: google-genai runs the MCP tool loop, tenacity does retries, aiogram does per-chat locking. `httpx2` is the only HTTP client used directly (plain `httpx` is not a dependency).
- `assistant.reply()` opens fresh MCP sessions per message (SSE for qBittorrent, streamable HTTP with bearer token for Jellyfin; 3 connect attempts, then an error reply) and passes the `ClientSession`s to a google-genai `AsyncChat` as `tools`. The SDK converts MCP schemas and executes tool calls (automatic function calling, max 10 calls). `_Session` works around two SDK bugs: `__deepcopy__` returns the live session (the SDK deep-copies its config), and `list_tools` drops boolean sub-schemas such as `"additionalProperties": false` (the SDK's schema filter crashes on them).
- Keyword routing: only the qBittorrent or only the Jellyfin MCP server is connected when only its keywords match; otherwise both. If the model still calls a tool of the unconnected server (e.g. one it saw in history), the SDK raises `KeyError`; `reply()` catches it (`except*`, since the MCP task groups wrap it) and reruns the message with both servers.
- Model fallback: `GEMINI_MODEL` accepts a comma-separated list in priority order. Any API error tries the next model; models that return 429 are skipped in-process for 8 hours.
- Overload retry: if every model fails with a 5xx (e.g. 503 UNAVAILABLE), the whole model list is retried after 2, 4, 8, 16, 32, 60 s. Before the first wait the user gets a one-time "Gemini is overloaded" notice.
- History: loaded from SQLite (last `HISTORY_LIMIT` rows) on every message; the new turns (user, tool calls/responses, model) are saved in one transaction only after a successful reply. Parts are (de)serialized with a pydantic `TypeAdapter`.
- The Dispatcher uses `SimpleEventIsolation` + `FSMStrategy.CHAT`, so messages in one chat are handled one at a time (consistent history) while different chats run concurrently.
- `.torrent` files bypass Gemini: `main._add_torrent` logs into the qBittorrent Web API and uploads the file with `httpx2`.
- All Telegram replies go through `_safe_reply` to prevent `TelegramNetworkError` from crashing the handler. Error replies unwrap single-exception `ExceptionGroup`s raised by the MCP transports' anyio task groups.
- CI smoke test: `pip check` plus `python -c "import main"` (with dummy secrets) inside the built image.

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
| `HISTORY_LIMIT` | no | Max conversation turns kept in SQLite and sent to the LLM (default: `20`) |
| `QBIT_KEYWORDS` | no | Comma-separated keywords (UTF-8) that route to qBittorrent-only tools (default: torrent, magnet, download, …) |
| `JELLYFIN_KEYWORDS` | no | Comma-separated keywords (UTF-8) that route to Jellyfin-only tools (default: movie, series, stream, …) |
| `QBIT_MCP_URL` | no | qBittorrent MCP SSE URL (default: `http://qbittorrent-mcp:3000/sse`) |
| `JELLYFIN_MCP_URL` | no | Jellyfin MCP URL (default: `http://jellyfin-mcp:8080/mcp`) |
| `TZ` | no | Timezone (default: `Europe/London`) |

Empty values (e.g. unset `${VAR}` passed through docker-compose) fall back to the defaults (`env_ignore_empty`).

| `QBIT_BLKIO_DRIVE` | no | Drive node to throttle for qBittorrent blkio limits (default: `/dev/sda`) |
| `QBIT_BLKIO_READ_BPS` | no | Byte-per-second read limit for blkio (default: `20971520` = 20 MiB/s) |
| `QBIT_BLKIO_WRITE_BPS` | no | Byte-per-second write limit for blkio (default: `20971520` = 20 MiB/s) |
| `QBIT_BLKIO_READ_IOPS` | no | Read IOPS limit for blkio (default: `50`) |
| `QBIT_BLKIO_WRITE_IOPS` | no | Write IOPS limit for blkio (default: `50`) |

## Runtime Volumes

Docker creates these at startup — they are gitignored:

- `./downloads/` — shared download directory (Samba + Jellyfin serve this)
- `./data/` — bot runtime data: `history.db` (per-chat conversation history)
- `./config/qbittorrent/` — qBittorrent config persistence
- `./config/jellyfin/` — Jellyfin config persistence; `jellyfin.env` holds the Jellyfin API key

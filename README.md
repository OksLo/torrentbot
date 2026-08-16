# Torrent Bot

Self-hosted media stack: a Telegram AI assistant that accepts natural language commands, magnet links, and torrent files, downloads them via qBittorrent, and serves the result over SMB (Windows/Mac file sharing) and Jellyfin (streaming). The bot is powered by Google Gemini and controls qBittorrent and Jellyfin via MCP tools.

## Services

| Service | Port | Purpose |
|---|---|---|
| qBittorrent Web UI | 8080 | Torrent client + management |
| Jellyfin | 8096 | Media streaming (browser, TV apps) |
| Samba | 445 | SMB file share for PCs |
| Telegram bot | — | AI assistant: natural language, magnet links, `.torrent` files |

## Prerequisites

- Docker and Docker Compose
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A Google Gemini API key

## Deployment

**1. Clone the repository**

```bash
git clone https://github.com/OksLo/torrentbot.git
cd torrentbot
```

**2. Configure environment**

```bash
cp .env.example .env
```

Edit `.env` and fill in:

```
BOT_TOKEN=your_telegram_bot_token_here
QBIT_USERNAME=admin
QBIT_PASSWORD=change_me
JELLYFIN_USERNAME=admin
JELLYFIN_PASSWORD=change_me
GEMINI_API_KEY=your_gemini_api_key_here
MCP_HTTP_TOKEN=change_me
TZ=Europe/London
```

Optionally set `GEMINI_MODEL` to a comma-separated list of models in priority order (e.g. `gemini-2.5-pro,gemini-2.5-flash`). The bot tries them in order and skips models that have hit their rate limit for 8 hours.

**3. Start all services**

```bash
make up
```

**4. Wait for automatic setup to complete**

On first boot, a `setup` container starts automatically once qBittorrent and Jellyfin are healthy. It sets passwords, creates the Jellyfin admin account, adds the Downloads library, and wires up autorun. Watch progress with:

```bash
make logs
```

## Usage

Send your bot any natural language request — it uses Gemini AI with access to qBittorrent and Jellyfin tools. You can also send magnet links or `.torrent` files directly.

Examples:
- _"Show active downloads"_
- _"What's been added to Jellyfin recently?"_
- _"Update the metadata for Inception"_

## Useful Commands

```bash
make up           # start all services (runs first-time setup automatically)
make down         # stop all services
make logs         # tail logs for all services
make bot-logs     # tail bot logs only
make restart-bot  # restart the bot container
make upgrade      # pull latest images and recreate services
```

## GPU Hardware Transcoding (Intel)

If the host has an Intel GPU (`/dev/dri` present), `make up` automatically enables VA-API hardware transcoding in Jellyfin — no manual configuration needed. The Makefile detects the GPU at startup and applies the overlay; on hosts without `/dev/dri` the stack runs normally.

## Connecting via SMB

The `downloads/` directory is shared as `\\<host-ip>\downloads` (read-only, no password required).

- **Windows**: open File Explorer → address bar → `\\<host-ip>\downloads`
- **macOS**: Finder → Go → Connect to Server → `smb://<host-ip>/downloads`

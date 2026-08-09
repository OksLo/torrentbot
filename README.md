# Torrent Bot

Self-hosted media stack: a Telegram bot that accepts magnet links and torrent files, downloads them via qBittorrent, and serves the result over SMB (Windows/Mac file sharing) and Jellyfin (streaming).

## Services

| Service | Port | Purpose |
|---|---|---|
| qBittorrent Web UI | 8080 | Torrent client + management |
| Jellyfin | 8096 | Media streaming (browser, TV apps) |
| Samba | 445 | SMB file share for PCs |
| Telegram bot | — | Accepts magnet links and `.torrent` files |

## Prerequisites

- Docker and Docker Compose
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

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
TZ=Europe/London
```

**3. Start all services**

```bash
make up
```

**4. Wait for automatic setup to complete**

On first boot, a `setup` container starts automatically once qBittorrent and Jellyfin are healthy. It sets the qBittorrent Web UI password, creates the Jellyfin admin account, and adds the Downloads library. Watch progress with:

```bash
make logs
```

The setup container exits when done and is skipped on all subsequent restarts.

## Usage

Send your bot a magnet link or a `.torrent` file. Use `/status` to check active downloads and `/help` for available commands.

## Useful Commands

```bash
make up           # start all services (runs first-time setup automatically)
make down         # stop all services
make logs         # tail logs for all services
make bot-logs     # tail bot logs only
make restart-bot  # restart the bot container
make upgrade      # pull latest images and recreate services so setup reruns
```

## Connecting via SMB

The `downloads/` directory is shared as `\\<host-ip>\downloads` (read-only, no password required).

- **Windows**: open File Explorer → address bar → `\\<host-ip>\downloads`
- **macOS**: Finder → Go → Connect to Server → `smb://<host-ip>/downloads`

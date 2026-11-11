"""AceStream channels as Gemini tools, stored in an M3U playlist that Jellyfin reads as a Live TV tuner."""
import re
from pathlib import Path

import httpx2

from config import settings

_playlist = Path(settings.acestream_playlist)
_content_id = re.compile(r"[0-9a-f]{40}")


def _read() -> dict[str, str]:
    """Return {channel name: content id}; the playlist alternates '#EXTINF:-1,<name>' and stream URL lines."""
    lines = _playlist.read_text().splitlines()[1:] if _playlist.exists() else []
    return {info.split(",", 1)[1]: url.rsplit("=", 1)[1] for info, url in zip(lines[::2], lines[1::2])}


async def _write(channels: dict[str, str]) -> None:
    entries = [f"#EXTINF:-1,{name}\n{settings.acestream_url}/ace/getstream?id={cid}" for name, cid in sorted(channels.items())]
    _playlist.write_text("\n".join(["#EXTM3U", *entries]) + "\n")
    # Jellyfin re-reads tuner playlists in its "Refresh Guide" task (otherwise it runs once a day)
    auth = {"Authorization": f'MediaBrowser Token="{settings.jellyfin_api_key}"'}
    async with httpx2.AsyncClient(base_url=settings.jellyfin_url, headers=auth) as jellyfin:
        tasks = (await jellyfin.get("/ScheduledTasks")).raise_for_status().json()
        task_id = next(task["Id"] for task in tasks if task["Key"] == "RefreshGuide")
        (await jellyfin.post(f"/ScheduledTasks/Running/{task_id}")).raise_for_status()


def list_acestream_channels() -> dict[str, str]:
    """List the AceStream channels shown in Jellyfin Live TV, as {channel name: content id}."""
    return _read()


async def add_acestream_channel(name: str, content_id: str) -> str:
    """Add an AceStream channel to Jellyfin Live TV, or replace the one with the same name.

    Args:
        name: Channel name shown in Jellyfin.
        content_id: AceStream content id (40 hex characters) or an acestream:// link.
    """
    match = _content_id.search(content_id.lower())
    if not match:
        return "Invalid AceStream content id: expected 40 hex characters."
    await _write(_read() | {name: match.group()})
    return f"Channel {name} added."


async def remove_acestream_channel(name: str) -> str:
    """Remove an AceStream channel from Jellyfin Live TV.

    Args:
        name: Exact channel name, as returned by list_acestream_channels.
    """
    channels = _read()
    if channels.pop(name, None) is None:
        return f"Channel {name} not found."
    await _write(channels)
    return f"Channel {name} removed."


TOOLS = [list_acestream_channels, add_acestream_channel, remove_acestream_channel]

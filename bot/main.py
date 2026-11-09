import asyncio
import logging

import httpx2
from aiogram import Bot, Dispatcher, F
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.fsm.strategy import FSMStrategy
from aiogram.types import Message

import assistant
import history
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Per-chat lock around each handler: messages in one chat are processed in order
# (keeps history consistent), different chats run concurrently.
dp = Dispatcher(events_isolation=SimpleEventIsolation(), fsm_strategy=FSMStrategy.CHAT)


async def _safe_reply(message: Message, text: str, **kwargs):
    try:
        await message.reply(text, **kwargs)
    except Exception as e:
        logger.exception(
            "failed to send reply to chat_id=%s text_len=%d text_preview=%r error=%s",
            message.chat.id,
            len(text),
            text[:100],
            e,
        )


async def _add_torrent(data: bytes) -> bool:
    async with httpx2.AsyncClient(base_url=settings.qbit_host) as qbit:
        await qbit.post(
            "/api/v2/auth/login",
            data={"username": settings.qbit_username, "password": settings.qbit_password},
        )
        resp = await qbit.post(
            "/api/v2/torrents/add",
            files={"torrents": ("file.torrent", data, "application/x-bittorrent")},
            data={"savepath": settings.download_path},
        )
        return resp.text == "Ok."


@dp.message(F.document.mime_type == "application/x-bittorrent")
async def handle_torrent_file(message: Message):
    await _safe_reply(message, "Processing .torrent file...")
    try:
        data = await message.bot.download(message.document)
        ok = await _add_torrent(data.read())
        await _safe_reply(message, "Torrent added." if ok else "Failed to add torrent.")
    except Exception:
        logger.exception("torrent file upload failed")
        await _safe_reply(message, "Failed to upload torrent file.")


@dp.message()
async def handle_message(message: Message):
    text = message.text or message.caption or ""
    if not text:
        return
    try:
        reply = await assistant.reply(
            message.chat.id,
            text,
            on_overloaded=lambda: _safe_reply(
                message, "Gemini is overloaded right now — I'll answer as soon as it's available."
            ),
        )
        await _safe_reply(message, reply, parse_mode="HTML")
    except Exception as e:
        logger.exception("assistant reply failed")
        # MCP transports run on anyio task groups, which wrap errors in ExceptionGroups
        while isinstance(e, ExceptionGroup) and len(e.exceptions) == 1:
            e = e.exceptions[0]
        await _safe_reply(message, f"Something went wrong [{type(e).__name__}]: {e}")


async def main():
    history.init_db()
    await dp.start_polling(Bot(token=settings.bot_token))


if __name__ == "__main__":
    asyncio.run(main())

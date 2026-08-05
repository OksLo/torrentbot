import logging

from aiogram import F, Router
from aiogram.types import Message
from google import genai
from google.genai import types
from mcp import ClientSession

from config import settings
from services import history
from services.qbittorrent import qbittorrent

router = Router()
logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are a helpful assistant for a self-hosted media server. "
    "You can manage torrents via qBittorrent and browse/search media via Jellyfin. "
    "Be concise. When asked about downloads or media, use your available tools."
)

gemini_client: genai.Client = None
qbit_session: ClientSession = None
jellyfin_session: ClientSession = None
all_tools: list = []
tool_to_session: dict[str, ClientSession] = {}
_history_cache: dict[int, list] = {}


@router.message(F.document.mime_type == "application/x-bittorrent")
async def handle_torrent_file(message: Message):
    await message.reply("Processing .torrent file...")
    try:
        file = await message.bot.get_file(message.document.file_id)
        data = await message.bot.download_file(file.file_path)
        ok = await qbittorrent.add_torrent_file(data.read())
        await message.reply("Torrent added." if ok else "Failed to add torrent.")
    except Exception:
        logger.exception("torrent file upload failed")
        await message.reply("Failed to upload torrent file.")


@router.message()
async def handle_message(message: Message):
    text = message.text or message.caption or ""
    if not text:
        return
    try:
        reply = await _gemini_loop(message.chat.id, text)
        await message.reply(reply)
    except Exception:
        logger.exception("gemini loop failed")
        await message.reply("Something went wrong. Please try again.")


async def _gemini_loop(chat_id: int, user_text: str) -> str:
    if chat_id not in _history_cache:
        _history_cache[chat_id] = history.load_history(chat_id)
    hist = _history_cache[chat_id]

    user_content = types.Content(role="user", parts=[types.Part(text=user_text)])
    hist.append(user_content)
    history.append_turn(chat_id, "user", user_content.parts)

    cfg = types.GenerateContentConfig(
        system_instruction=_SYSTEM,
        tools=all_tools or None,
    )

    while True:
        response = await gemini_client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=hist,
            config=cfg,
        )
        model_content = response.candidates[0].content
        hist.append(model_content)
        history.append_turn(chat_id, model_content.role, model_content.parts)

        fn_calls = [p for p in model_content.parts if p.function_call is not None]
        if not fn_calls:
            return response.text or "(no response)"

        fn_parts = []
        for p in fn_calls:
            fc = p.function_call
            session = tool_to_session.get(fc.name)
            if session is None:
                result_text = f"Tool '{fc.name}' is not available."
            else:
                try:
                    result = await session.call_tool(fc.name, dict(fc.args))
                    result_text = "\n".join(
                        c.text for c in result.content if hasattr(c, "text") and c.text
                    ) or "(no output)"
                except Exception as e:
                    logger.exception("MCP tool call failed: %s", fc.name)
                    result_text = f"Tool error: {e}"
            fn_parts.append(types.Part(
                function_response=types.FunctionResponse(
                    name=fc.name, response={"result": result_text}
                )
            ))

        tool_content = types.Content(role="user", parts=fn_parts)
        hist.append(tool_content)
        history.append_turn(chat_id, "user", tool_content.parts)

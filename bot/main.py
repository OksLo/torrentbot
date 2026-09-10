import asyncio
import logging

import httpx2
from aiogram import Bot, Dispatcher
from google import genai
from google.genai import types
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from config import settings
from handlers import ai
from services import history

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


_GEMINI_SCHEMA_KEYS = {"type", "format", "description", "nullable", "enum", "properties", "required", "items"}


def _sanitize_schema(schema: dict) -> dict:
    if not isinstance(schema, dict):
        return schema
    result = {}
    for k, v in schema.items():
        if k not in _GEMINI_SCHEMA_KEYS:
            continue
        if k == "type" and isinstance(v, list):
            non_null = [t for t in v if t != "null"]
            result[k] = non_null[0] if non_null else "string"
        elif k == "properties" and isinstance(v, dict):
            # values are property-name → schema maps, not schema keyword dicts
            result[k] = {name: _sanitize_schema(prop_schema) for name, prop_schema in v.items()}
        elif isinstance(v, dict):
            result[k] = _sanitize_schema(v)
        elif isinstance(v, list):
            result[k] = [_sanitize_schema(i) if isinstance(i, dict) else i for i in v]
        else:
            result[k] = v
    return result


def _build_gemini_tools(mcp_tools) -> list:
    decls = []
    for t in mcp_tools:
        schema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None)
        if schema is None:
            schema = {"type": "object", "properties": {}}
        decls.append(types.FunctionDeclaration(
            name=t.name,
            description=t.description or "",
            parameters=_sanitize_schema(schema),
        ))
    return [types.Tool(function_declarations=decls)] if decls else []


async def _mcp_loop():
    """Hold the MCP sessions open, reconnecting whenever one drops.

    Runs for the lifetime of the process, independently of Telegram polling.
    While a reconnect is in flight the tool registries are empty and the Gemini
    loop simply answers without tools.
    """
    while True:
        try:
            async with sse_client(settings.qbit_mcp_url) as (qbit_read, qbit_write):
                async with ClientSession(qbit_read, qbit_write) as qbit_sess:
                    await qbit_sess.initialize()
                    ai.qbit_session = qbit_sess

                    async with httpx2.AsyncClient(
                        headers={"Authorization": f"Bearer {settings.mcp_http_token}"},
                    ) as jf_http_client:
                        async with streamable_http_client(
                            settings.jellyfin_mcp_url,
                            http_client=jf_http_client,
                        ) as (jf_read, jf_write):
                            async with ClientSession(jf_read, jf_write) as jf_sess:
                                await jf_sess.initialize()
                                ai.jellyfin_session = jf_sess

                                qbit_tools = (await qbit_sess.list_tools()).tools
                                jf_tools = (await jf_sess.list_tools()).tools
                                logger.info("qBit MCP tools: %s", [t.name for t in qbit_tools])
                                logger.info("Jellyfin MCP tools: %s", [t.name for t in jf_tools])

                                ai.tool_to_session = {t.name: qbit_sess for t in qbit_tools}
                                ai.tool_to_session.update({t.name: jf_sess for t in jf_tools})
                                ai.qbit_tools = _build_gemini_tools(qbit_tools)
                                ai.jf_tools = _build_gemini_tools(jf_tools)
                                ai.all_tools = _build_gemini_tools(qbit_tools + jf_tools)

                                reconnect_needed = asyncio.Event()
                                ai.reconnect_event = reconnect_needed

                                # Park here until a tool call reports the session
                                # is gone, then fall through to the reconnect.
                                await reconnect_needed.wait()
                                raise RuntimeError("MCP session terminated")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("MCP connection lost, reconnecting in 5s...")
            ai.all_tools = []
            ai.qbit_tools = []
            ai.jf_tools = []
            ai.tool_to_session = {}
            ai.reconnect_event = None
            await asyncio.sleep(5)


async def main():
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    history.init_db(settings.history_db_path)
    ai.gemini_client = genai.Client(api_key=settings.gemini_api_key)
    dp.include_router(ai.router)

    # MCP connectivity is independent of Telegram polling, so it gets its own
    # task. Polling must be started exactly once per process: starting it per
    # MCP reconnect leaves orphaned getUpdates loops behind, and Telegram
    # rejects concurrent pollers with TelegramConflictError.
    mcp_task = asyncio.create_task(_mcp_loop())
    try:
        await dp.start_polling(bot)
    finally:
        mcp_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())

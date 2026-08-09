import asyncio
import logging

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


def _build_gemini_tools(mcp_tools) -> list:
    decls = []
    for t in mcp_tools:
        schema = t.inputSchema if t.inputSchema else {"type": "object", "properties": {}}
        decls.append(types.FunctionDeclaration(
            name=t.name,
            description=t.description or "",
            parameters=schema,
        ))
    return [types.Tool(function_declarations=decls)] if decls else []


async def main():
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    history.init_db(settings.history_db_path)
    ai.gemini_client = genai.Client(api_key=settings.gemini_api_key)

    async with sse_client(settings.qbit_mcp_url) as (qbit_read, qbit_write):
        async with ClientSession(qbit_read, qbit_write) as qbit_sess:
            await qbit_sess.initialize()
            ai.qbit_session = qbit_sess

            async with streamable_http_client(
                settings.jellyfin_mcp_url,
                headers={"Authorization": f"Bearer {settings.mcp_http_token}"},
            ) as (jf_read, jf_write, _):
                async with ClientSession(jf_read, jf_write) as jf_sess:
                    await jf_sess.initialize()
                    ai.jellyfin_session = jf_sess

                    qbit_tools = (await qbit_sess.list_tools()).tools
                    jf_tools = (await jf_sess.list_tools()).tools
                    logger.info("qBit MCP tools: %s", [t.name for t in qbit_tools])
                    logger.info("Jellyfin MCP tools: %s", [t.name for t in jf_tools])

                    ai.tool_to_session = {t.name: qbit_sess for t in qbit_tools}
                    ai.tool_to_session.update({t.name: jf_sess for t in jf_tools})
                    ai.all_tools = _build_gemini_tools(qbit_tools + jf_tools)

                    dp.include_router(ai.router)
                    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

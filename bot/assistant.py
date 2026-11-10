import logging
import time
from contextlib import AsyncExitStack
from typing import Awaitable, Callable

import httpx2
from google import genai
from google.genai import errors, types
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from tenacity import AsyncRetrying, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

import history
from config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a helpful assistant for a self-hosted media server. "
    "You can manage torrents via qBittorrent and browse/search media via Jellyfin. "
    "Be concise. When asked about downloads or media, use your available tools.\n\n"

    "Format ALL responses as Telegram HTML (parse_mode=HTML). Supported tags only:\n"
    "- <b>bold</b> for labels, headings, torrent/media names\n"
    "- <i>italic</i> for secondary info, dates, status\n"
    "- <code>inline code</code> for hashes, IDs, paths\n"
    "- <pre>preformatted block</pre> for tabular data — use fixed-width columns "
    "padded with spaces, e.g.:\n"
    "<pre>\n"
    "Name               Size    Progress  State\n"
    "Movie 2024         10.2GB  100%      Seeding\n"
    "Series S01E01      4.5GB    60%      Downloading\n"
    "</pre>\n"
    "Always escape & as &amp;, < as &lt;, > as &gt; in plain text content. "
    "Never use Markdown syntax (* _ ` #). Never use unsupported HTML tags.\n\n"

    "When asked to update the metadata of a movie, find it's IMDb page and use the "
    "IMDb ID to update the metadata via jellyfin_metadata tool. "
    "Update the metadata only if the IMDb ID is found. If not found, respond with 'IMDb ID not found.'."
    "Update the movie poster using the remote_download action of the jellyfin_images tool."
    "Use IMDB as poster source.\n\n"
)

_client = genai.Client(api_key=settings.gemini_api_key)
_jellyfin_http = httpx2.AsyncClient(
    headers={"Authorization": f"Bearer {settings.mcp_http_token}"},
    timeout=httpx2.Timeout(30, read=300),  # MCP SDK defaults; tool calls can be slow
)
_blocked_until: dict[str, float] = {}  # model -> unix time its 429 block expires
_BLOCK_SECONDS = 8 * 3600


def _drop_bool_schemas(schema):
    """Drop boolean sub-schemas (e.g. "additionalProperties": false), which crash google-genai's MCP schema filter."""
    if isinstance(schema, dict):
        return {
            key: _drop_bool_schemas(value)
            for key, value in schema.items()
            if not (key in ("items", "additionalProperties") and isinstance(value, bool))
        }
    if isinstance(schema, list):
        return [_drop_bool_schemas(value) for value in schema]
    return schema


class _Session(ClientSession):
    """ClientSession with workarounds for google-genai's MCP support."""

    def __deepcopy__(self, memo):  # the SDK deep-copies its config; a live session can't be copied
        return self

    async def list_tools(self, **kwargs):
        result = await super().list_tools(**kwargs)
        for tool in result.tools:
            tool.input_schema = _drop_bool_schemas(tool.input_schema)
        return result


def _servers_for(text: str) -> list[str]:
    """Route by keywords: one server if only its keywords match, otherwise both."""
    text = text.lower()
    qbit = any(kw in text for kw in settings.qbit_keyword_list)
    jellyfin = any(kw in text for kw in settings.jellyfin_keyword_list)
    if qbit and not jellyfin:
        return ["qbit"]
    if jellyfin and not qbit:
        return ["jellyfin"]
    return ["qbit", "jellyfin"]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(max=5), reraise=True)
async def _open(stack: AsyncExitStack, server: str) -> ClientSession:
    if server == "qbit":
        transport = sse_client(settings.qbit_mcp_url)
    else:
        transport = streamable_http_client(settings.jellyfin_mcp_url, http_client=_jellyfin_http)
    read, write = await stack.enter_async_context(transport)
    session = await stack.enter_async_context(_Session(read, write))
    await session.initialize()
    return session


async def _send(past: list[types.Content], text: str, config: types.GenerateContentConfig):
    """Send via the first model that isn't rate-limited; the SDK runs the MCP tool calls."""
    error: Exception = RuntimeError("All configured Gemini models are rate-limited")
    for model in settings.gemini_models:
        if _blocked_until.get(model, 0) > time.time():
            continue
        chat = _client.aio.chats.create(model=model, config=config, history=past)
        try:
            return chat, await chat.send_message(text)
        except errors.APIError as e:
            logger.warning("Model %s failed: %s", model, e)
            if e.code == 429:
                _blocked_until[model] = time.time() + _BLOCK_SECONDS
            error = e
    raise error


async def reply(chat_id: int, text: str, on_overloaded: Callable[[], Awaitable]) -> str:
    async def notify_once(state):
        if state.attempt_number == 1:
            await on_overloaded()

    past = history.load(chat_id)
    async with AsyncExitStack() as stack:
        tools = [await _open(stack, server) for server in _servers_for(text)]
        config = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, tools=tools)
        # 503 & co: retry all models after 2, 4, 8, 16, 32, 60 s (~2 min in total)
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(errors.ServerError),
            wait=wait_exponential(multiplier=2, max=60),
            stop=stop_after_attempt(7),
            before_sleep=notify_once,
            reraise=True,
        ):
            with attempt:
                chat, response = await _send(past, text, config)
    history.save(chat_id, chat.get_history()[len(past):])
    return response.text or "(no response)"

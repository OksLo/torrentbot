import json
import logging

from google.genai import types

from services import acestream_db

logger = logging.getLogger(__name__)

TOOL_NAMES = {
    "add_acestream_channel",
    "remove_acestream_channel",
    "list_acestream_channels",
    "get_acestream_stream_url",
}

gemini_tools = [types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="add_acestream_channel",
        description="Add or update an AceStream channel. Extracts the content ID from acestream:// links automatically.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Human-readable channel name, e.g. 'Sky News'"},
                "content_id": {"type": "string", "description": "AceStream content ID (40-char hex) or full acestream:// link"},
            },
            "required": ["name", "content_id"],
        },
    ),
    types.FunctionDeclaration(
        name="remove_acestream_channel",
        description="Remove an AceStream channel from the registry by name.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Exact channel name to remove"},
            },
            "required": ["name"],
        },
    ),
    types.FunctionDeclaration(
        name="list_acestream_channels",
        description="List all saved AceStream channels with their content IDs.",
        parameters={"type": "object", "properties": {}},
    ),
    types.FunctionDeclaration(
        name="get_acestream_stream_url",
        description="Get the HTTP stream URL for an AceStream channel. Use this when the user wants to watch a specific channel.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Channel name to get the stream URL for"},
            },
            "required": ["name"],
        },
    ),
])]


def dispatch(tool_name: str, args: dict) -> str:
    if tool_name == "add_acestream_channel":
        acestream_db.add_channel(args["name"], args["content_id"])
        return json.dumps({"status": "ok", "message": f"Channel '{args['name']}' saved."})

    if tool_name == "remove_acestream_channel":
        removed = acestream_db.remove_channel(args["name"])
        if removed:
            return json.dumps({"status": "ok", "message": f"Channel '{args['name']}' removed."})
        return json.dumps({"status": "not_found", "message": f"Channel '{args['name']}' not found."})

    if tool_name == "list_acestream_channels":
        channels = acestream_db.list_channels()
        return json.dumps({"channels": channels, "count": len(channels)})

    if tool_name == "get_acestream_stream_url":
        channels = acestream_db.list_channels()
        ch = next((c for c in channels if c["name"] == args["name"]), None)
        if not ch:
            return json.dumps({"status": "not_found", "message": f"Channel '{args['name']}' not found."})
        from config import settings
        url = f"{settings.acestream_engine_url}/ace/getstream?id={ch['content_id']}&format=ts"
        return json.dumps({"status": "ok", "name": ch["name"], "stream_url": url})

    return json.dumps({"error": f"Unknown tool: {tool_name}"})

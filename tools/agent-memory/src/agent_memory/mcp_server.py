from __future__ import annotations

import json
import sys
from uuid import UUID

from .cli import result, service_from_env
from .model import (AddRequest, DeleteRequest, ListQuery, MemoryError, SearchQuery,
                    UpdateRequest)


TOOLS = ("memory_add", "memory_search", "memory_get", "memory_list", "memory_update", "memory_delete", "memory_status")


def call(service, name: str, arguments: dict):
    if name == "memory_add":
        return service.add(AddRequest(arguments["request_id"], arguments["type"], arguments["scope"], arguments["content"], arguments.get("project"), arguments.get("importance", 0.5), arguments.get("confidence", 1.0), arguments.get("pinned", False), tuple(arguments.get("tags", ()))))
    if name == "memory_search":
        return service.search(SearchQuery(arguments["query"], arguments.get("project")))
    if name == "memory_get":
        return service.get(UUID(arguments["id"]))
    if name == "memory_list":
        return service.list(ListQuery(arguments.get("project"), arguments.get("scope"), arguments.get("type")))
    if name == "memory_update":
        return service.update(UpdateRequest(UUID(arguments["id"]), arguments["expected_revision"], arguments["expected_content_hash"], arguments["request_id"], arguments.get("content"), arguments.get("importance"), arguments.get("confidence"), arguments.get("pinned"), tuple(arguments["tags"]) if "tags" in arguments else None))
    if name == "memory_delete":
        return service.delete(DeleteRequest(UUID(arguments["id"]), arguments["expected_revision"], arguments["expected_content_hash"], arguments["request_id"]))
    if name == "memory_status":
        return {"status": "ok"}
    raise MemoryError("unknown_tool", f"unknown tool {name}")


def respond(value: dict) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> None:
    service = service_from_env()
    for line in sys.stdin:
        request = None
        try:
            request = json.loads(line)
            method = request.get("method")
            if method == "initialize":
                response = {"jsonrpc": "2.0", "id": request.get("id"), "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}}
            elif method == "tools/list":
                response = {"jsonrpc": "2.0", "id": request.get("id"), "result": {"tools": [{"name": name, "inputSchema": {"type": "object"}} for name in TOOLS]}}
            elif method == "tools/call":
                value = result(call(service, request["params"]["name"], request["params"].get("arguments", {})))
                response = {"jsonrpc": "2.0", "id": request.get("id"), "result": {"content": [{"type": "text", "text": json.dumps(value, separators=(",", ":"))}]}}
            else:
                raise MemoryError("method_not_found", f"unsupported method {method}")
        except MemoryError as error:
            response = {"jsonrpc": "2.0", "id": request.get("id") if request else None, "error": {"code": -32000, "message": error.message, "data": {"code": error.code}}}
        except (KeyError, ValueError, TypeError) as error:
            print(str(error), file=sys.stderr)
            response = {"jsonrpc": "2.0", "id": request.get("id") if request else None, "error": {"code": -32602, "message": str(error), "data": {"code": "invalid_request"}}}
        respond(response)


if __name__ == "__main__":
    main()

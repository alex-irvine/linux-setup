from __future__ import annotations

import json
import sys
from uuid import UUID

from .cli import result, service_from_env
from .model import (AddRequest, DeleteRequest, FeedbackRequest, ListQuery, MemoryError,
                    PinRequest, ScopeRequest, SearchQuery, UpdateRequest)


TOOLS = ("memory_add", "memory_search", "memory_get", "memory_list", "memory_update", "memory_delete", "memory_status",
         "memory_feedback", "memory_pin", "memory_scope", "memory_rebuild", "memory_reconcile", "memory_maintain",
         "memory_delete_all", "memory_purge")


def call(service, name: str, arguments: dict, client: str = "unknown"):
    if name == "memory_add":
        return service.add(AddRequest(arguments["request_id"], arguments["type"], arguments["scope"], arguments["content"], arguments.get("project"), arguments.get("importance", 0.5), arguments.get("confidence", 1.0), arguments.get("pinned", False), tuple(arguments.get("tags", ())), client))
    if name == "memory_search":
        return service.search(SearchQuery(arguments["query"], arguments.get("project"), arguments.get("status", "active"), arguments.get("scope"), arguments.get("type"), tuple(arguments.get("tags", ()))))
    if name == "memory_get":
        return service.get(UUID(arguments["id"]))
    if name == "memory_list":
        return service.list(ListQuery(arguments.get("project"), arguments.get("scope"), arguments.get("type"), arguments.get("status", "active")))
    if name == "memory_update":
        return service.update(UpdateRequest(UUID(arguments["id"]), arguments["expected_revision"], arguments["expected_content_hash"], arguments["request_id"], arguments.get("content"), arguments.get("importance"), arguments.get("confidence"), arguments.get("pinned"), tuple(arguments["tags"]) if "tags" in arguments else None, arguments.get("status")))
    if name == "memory_delete":
        return service.delete(DeleteRequest(UUID(arguments["id"]), arguments["expected_revision"], arguments["expected_content_hash"], arguments["request_id"]))
    if name == "memory_status":
        return service.status()
    if name == "memory_pin":
        return service.pin(PinRequest(UUID(arguments["id"]), arguments["expected_revision"], arguments["expected_content_hash"], arguments["request_id"], arguments["pinned"]))
    if name == "memory_scope":
        return service.scope(ScopeRequest(UUID(arguments["id"]), arguments["expected_revision"], arguments["expected_content_hash"], arguments["request_id"], arguments["scope"], arguments.get("project")))
    if name == "memory_feedback":
        return service.feedback(FeedbackRequest(UUID(arguments["id"]), arguments["request_id"], arguments["rating"]))
    if name == "memory_rebuild":
        return service.rebuild()
    if name == "memory_reconcile":
        return service.reconcile()
    if name == "memory_maintain":
        return service.maintain()
    if name == "memory_delete_all":
        return service.delete_all(arguments["request_id"], arguments["token"])
    if name == "memory_purge":
        if arguments.get("confirm_history_rewrite") is not True:
            raise MemoryError("invalid_request", "purge requires confirm_history_rewrite=true")
        return service.purge(arguments["request_id"], arguments["token"], UUID(arguments["memory_id"]), arguments["content_hash"])
    raise MemoryError("unknown_tool", f"unknown tool {name}")


def respond(value: dict) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main(client: str = "unknown") -> None:
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
                value = result(call(service, request["params"]["name"], request["params"].get("arguments", {}), client))
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

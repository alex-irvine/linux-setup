from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import UUID

from .index import MemoryIndex
from .model import (AddRequest, DeleteRequest, FeedbackRequest, ListQuery, MemoryError,
                    PinRequest, ScopeRequest, SearchQuery, UpdateRequest)
from .store import MarkdownStore, MemoryService


def service_from_env() -> MemoryService:
    home = Path(os.environ.get("AGENT_MEMORY_HOME", Path.home() / ".local/share/agent-memory"))
    vault = Path(os.environ.get("AGENT_MEMORY_VAULT", Path.home() / ".agents/memory"))
    return MemoryService(MarkdownStore(vault, home), MemoryIndex(home / "memory.sqlite3"))


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def parser() -> argparse.ArgumentParser:
    root = JsonArgumentParser(prog="memoryctl")
    commands = root.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add")
    add.add_argument("--request-id", required=True)
    add.add_argument("--type", required=True)
    add.add_argument("--scope", required=True)
    add.add_argument("--project")
    add.add_argument("--content", required=True)
    add.add_argument("--importance", type=float, default=0.5)
    add.add_argument("--confidence", type=float, default=1.0)
    add.add_argument("--pinned", action="store_true")
    add.add_argument("--tag", action="append", default=[])
    for name in ("get", "list", "search", "update", "delete", "status", "pin", "scope",
                 "feedback", "rebuild", "reconcile", "maintain", "delete-all", "purge"):
        commands.add_parser(name)
    commands.choices["get"].add_argument("--id", required=True)
    commands.choices["list"].add_argument("--project")
    commands.choices["list"].add_argument("--scope")
    commands.choices["list"].add_argument("--type")
    commands.choices["list"].add_argument("--status", default="active")
    commands.choices["search"].add_argument("--query", required=True)
    commands.choices["search"].add_argument("--project")
    commands.choices["search"].add_argument("--status", default="active")
    commands.choices["search"].add_argument("--scope")
    commands.choices["search"].add_argument("--type")
    commands.choices["search"].add_argument("--tag", action="append", default=[])
    update = commands.choices["update"]
    update.add_argument("--id", required=True)
    update.add_argument("--expected-revision", type=int, required=True)
    update.add_argument("--expected-content-hash", required=True)
    update.add_argument("--request-id", required=True)
    update.add_argument("--content")
    update.add_argument("--importance", type=float)
    update.add_argument("--confidence", type=float)
    update.add_argument("--pinned", action=argparse.BooleanOptionalAction, default=None)
    update.add_argument("--tag", action="append")
    update.add_argument("--status")
    delete = commands.choices["delete"]
    delete.add_argument("--id", required=True)
    delete.add_argument("--expected-revision", type=int, required=True)
    delete.add_argument("--expected-content-hash", required=True)
    delete.add_argument("--request-id", required=True)
    pin = commands.choices["pin"]
    pin.add_argument("--id", required=True)
    pin.add_argument("--request-id", required=True)
    pin.add_argument("--expected-revision", type=int, required=True)
    pin.add_argument("--expected-content-hash", required=True)
    pin.add_argument("--pinned", action=argparse.BooleanOptionalAction, required=True)
    scope = commands.choices["scope"]
    scope.add_argument("--id", required=True)
    scope.add_argument("--request-id", required=True)
    scope.add_argument("--expected-revision", type=int, required=True)
    scope.add_argument("--expected-content-hash", required=True)
    scope.add_argument("--scope", required=True)
    scope.add_argument("--project")
    feedback = commands.choices["feedback"]
    feedback.add_argument("--id", required=True)
    feedback.add_argument("--request-id", required=True)
    feedback.add_argument("--rating", required=True)
    delete_all = commands.choices["delete-all"]
    delete_all.add_argument("--request-id", required=True)
    delete_all.add_argument("--token", required=True)
    purge = commands.choices["purge"]
    purge.add_argument("--request-id", required=True)
    purge.add_argument("--token", required=True)
    purge.add_argument("--memory-id", required=True)
    purge.add_argument("--content-hash", required=True)
    purge.add_argument("--confirm-history-rewrite", action="store_true")
    admin = commands.add_parser("admin")
    admin_commands = admin.add_subparsers(dest="admin_command", required=True)
    authorize = admin_commands.add_parser("authorize")
    authorize.add_argument("--action", required=True, choices=("delete-all", "purge"))
    authorize.add_argument("--ttl", type=int, default=60)
    return root


def result(value):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, list):
        return {"memories": [item.to_dict() for item in value]}
    return value


def dispatch(service: MemoryService, args: argparse.Namespace):
    if args.command == "add":
        return service.add(AddRequest(args.request_id, args.type, args.scope, args.content, args.project, args.importance, args.confidence, args.pinned, tuple(args.tag)))
    if args.command == "get":
        return service.get(UUID(args.id))
    if args.command == "list":
        return service.list(ListQuery(args.project, args.scope, args.type, args.status))
    if args.command == "search":
        return service.search(SearchQuery(args.query, args.project, args.status, args.scope, args.type, tuple(args.tag)))
    if args.command == "update":
        return service.update(UpdateRequest(UUID(args.id), args.expected_revision, args.expected_content_hash, args.request_id, args.content, args.importance, args.confidence, args.pinned, tuple(args.tag) if args.tag is not None else None, args.status))
    if args.command == "delete":
        return service.delete(DeleteRequest(UUID(args.id), args.expected_revision, args.expected_content_hash, args.request_id))
    if args.command == "pin":
        return service.pin(PinRequest(UUID(args.id), args.expected_revision, args.expected_content_hash, args.request_id, args.pinned))
    if args.command == "scope":
        return service.scope(ScopeRequest(UUID(args.id), args.expected_revision, args.expected_content_hash, args.request_id, args.scope, args.project))
    if args.command == "feedback":
        return service.feedback(FeedbackRequest(UUID(args.id), args.request_id, args.rating))
    if args.command == "rebuild":
        return service.rebuild()
    if args.command == "reconcile":
        return service.reconcile()
    if args.command == "maintain":
        return service.maintain()
    if args.command == "status":
        return service.status()
    if args.command == "delete-all":
        return service.delete_all(args.request_id, args.token)
    if args.command == "purge":
        if not args.confirm_history_rewrite:
            raise MemoryError("invalid_request", "purge requires --confirm-history-rewrite")
        return service.purge(args.request_id, args.token, UUID(args.memory_id), args.content_hash)
    if args.command == "admin":
        return service.authorize(args.action, args.ttl)
    raise MemoryError("invalid_request", "unsupported command")


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        print(json.dumps({"ok": True, "result": result(dispatch(service_from_env(), args))}, separators=(",", ":")))
        return 0
    except MemoryError as error:
        print(json.dumps({"ok": False, "error": {"code": error.code, "message": error.message}}, separators=(",", ":")))
        return 1
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        print(json.dumps({"ok": False, "error": {"code": "invalid_request", "message": str(error)}}, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

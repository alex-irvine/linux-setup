from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from .index import MemoryIndex
from .capture import Outbox, Worker
from .migration import MigrationService
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
    add.add_argument("--request-id")
    add.add_argument("--type")
    add.add_argument("--scope")
    add.add_argument("--project")
    add.add_argument("--content")
    add.add_argument("--importance", type=float, default=0.5)
    add.add_argument("--confidence", type=float, default=1.0)
    add.add_argument("--pinned", action="store_true")
    add.add_argument("--tag", action="append", default=[])
    add.add_argument("--source-client", default="unknown")
    add.add_argument("--source-session", default="unknown")
    add.add_argument("--supersedes", action="append", default=[])
    add.add_argument("--json-input")
    for name in ("get", "list", "search", "update", "delete", "status", "pin", "scope",
                   "feedback", "rebuild", "reconcile", "maintain", "delete-all", "purge", "enqueue", "worker", "relocate-legacy"):
        commands.add_parser(name)
    commands.add_parser("mcp").add_argument("--client", required=True, choices=("claude", "opencode", "hermes", "pi"))
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
    commands.choices["status"].add_argument("--require-healthy", action="store_true")
    update = commands.choices["update"]
    update.add_argument("--id")
    update.add_argument("--expected-revision", type=int)
    update.add_argument("--expected-content-hash")
    update.add_argument("--request-id")
    update.add_argument("--content")
    update.add_argument("--importance", type=float)
    update.add_argument("--confidence", type=float)
    update.add_argument("--pinned", action=argparse.BooleanOptionalAction, default=None)
    update.add_argument("--tag", action="append")
    update.add_argument("--status")
    update.add_argument("--json-input")
    delete = commands.choices["delete"]
    delete.add_argument("--id")
    delete.add_argument("--expected-revision", type=int)
    delete.add_argument("--expected-content-hash")
    delete.add_argument("--request-id")
    delete.add_argument("--json-input")
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
    enqueue = commands.choices["enqueue"]
    enqueue.add_argument("--kind", required=True, choices=("capture", "sync"))
    enqueue.add_argument("--json-input", required=True)
    worker = commands.choices["worker"]
    worker_group = worker.add_mutually_exclusive_group(required=True)
    worker_group.add_argument("--once", action="store_true")
    worker_group.add_argument("--drain", action="store_true")
    sync = commands.add_parser("sync")
    sync_commands = sync.add_subparsers(dest="sync_command", required=True)
    pause = sync_commands.add_parser("pause")
    pause.add_argument("--reason", required=True)
    sync_commands.add_parser("resume")
    commands.choices["maintain"].add_argument("--security-scan", action="store_true")
    commands.choices["maintain"].add_argument("--fail-on-finding", action="store_true")
    migrate = commands.add_parser("migrate")
    migrate_commands = migrate.add_subparsers(dest="migrate_command", required=True)
    for name in ("snapshot", "import-local", "import-mem0", "report", "verify", "defer", "waive"):
        command = migrate_commands.add_parser(name)
        command.add_argument("--batch", required=True)
    migrate_commands.choices["import-local"].add_argument("--stop-after", type=int)
    migrate_commands.choices["import-mem0"].add_argument("--hosted-export")
    for name in ("defer", "waive"):
        command = migrate_commands.choices[name]
        command.add_argument("--source-identity", required=True)
        command.add_argument("--reason", required=True)
        command.add_argument("--decision", required=True)
    migrate_commands.choices["defer"].add_argument("--note-id", required=True)
    for command in commands.choices.values():
        command.add_argument("--json", action="store_true")
    return root


def result(value):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, list):
        return {"memories": [item.to_dict() for item in value]}
    return value


def dispatch(service: MemoryService, args: argparse.Namespace):
    if args.command == "add":
        return service.add(AddRequest(args.request_id, args.type, args.scope, args.content, args.project, args.importance, args.confidence, args.pinned, tuple(args.tag), args.source_client, args.source_session, tuple(args.supersedes)))
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
    if args.command == "relocate-legacy":
        return service.store.relocate_legacy()
    if args.command == "reconcile":
        return service.reconcile()
    if args.command == "maintain":
        return service.maintain(args.security_scan, args.fail_on_finding)
    if args.command == "status":
        value = service.status()
        if args.require_healthy and (value["invalid_notes"] or value["outbox"]["ready"] or value["outbox"]["running"] or value["sync_paused"] or value["sync_state"]["scheduling_error"]):
            raise MemoryError("unhealthy", "memory status has invalid notes, active outbox work, a paused sync, or a scheduling failure")
        return value
    if args.command == "delete-all":
        return service.delete_all(args.request_id, args.token)
    if args.command == "purge":
        if not args.confirm_history_rewrite:
            raise MemoryError("invalid_request", "purge requires --confirm-history-rewrite")
        return service.purge(args.request_id, args.token, UUID(args.memory_id), args.content_hash)
    if args.command == "admin":
        return service.authorize(args.action, args.ttl)
    if args.command == "enqueue":
        raw = sys.stdin.read() if args.json_input == "-" else Path(args.json_input).read_text(encoding="utf-8")
        return Outbox(service.store.home).enqueue(args.kind, json.loads(raw))
    if args.command == "worker":
        repo = Path(os.environ["AGENT_MEMORY_REPO"]) if os.environ.get("AGENT_MEMORY_REPO") else None
        return Worker(service, service.store.home, repo).run(args.drain)
    if args.command == "sync":
        marker = service.store.home / "sync-paused.json"
        if args.sync_command == "pause":
            from .capture import atomic_json
            with Outbox(service.store.home).locked():
                atomic_json(marker, {"reason": args.reason, "at": __import__("agent_memory.model", fromlist=["utc_now"]).utc_now()})
            return {"paused": True, "reason": args.reason}
        with Outbox(service.store.home).locked():
            marker.unlink(missing_ok=True)
            directory = os.open(marker.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return {"paused": False}
    if args.command == "migrate":
        migration = MigrationService(service, service.store.home)
        if args.migrate_command == "snapshot":
            return migration.snapshot(args.batch)
        if args.migrate_command == "import-local":
            return migration.import_local(args.batch, args.stop_after)
        if args.migrate_command == "import-mem0":
            pages = None
            if args.hosted_export:
                loaded = json.loads(Path(args.hosted_export).read_text(encoding="utf-8"))
                pages = loaded if isinstance(loaded, list) else [loaded]
            return migration.import_mem0(args.batch, pages)
        if args.migrate_command == "report":
            return migration.report(args.batch)
        if args.migrate_command in {"defer", "waive"}:
            return migration.disposition(args.batch, args.source_identity,
                                         "defer" if args.migrate_command == "defer" else "waive",
                                         args.reason, args.decision, getattr(args, "note_id", None))
        return migration.verify(args.batch)
    raise MemoryError("invalid_request", "unsupported command")


def apply_json_input(args: argparse.Namespace) -> None:
    path = getattr(args, "json_input", None)
    if path is None:
        return
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    values = json.loads(raw)
    if not isinstance(values, dict):
        raise ValueError("JSON input must be an object")
    for key, value in values.items():
        if key == "tags":
            args.tag = value
        elif key in vars(args):
            setattr(args, key, value)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        if args.command == "mcp":
            from .mcp_server import main as mcp_main
            mcp_main(args.client)
            return 0
        if args.command in {"add", "update", "delete"}:
            apply_json_input(args)
        service = service_from_env()
        value = dispatch(service, args)
        if args.command in {"add", "update", "delete", "pin", "scope", "purge", "delete-all"}:
            try:
                Worker(service, service.store.home, Path(os.environ["AGENT_MEMORY_REPO"]) if os.environ.get("AGENT_MEMORY_REPO") else None).ensure_dirty_sync()
                if shutil.which("systemctl"):
                    wake = subprocess.run(["systemctl", "--user", "start", "--no-block", "agent-memory-worker.service"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if wake.returncode:
                        raise OSError("agent-memory worker wakeup failed")
            except (OSError, ValueError) as error:
                service.store.scheduling_failed(error)
        print(json.dumps({"ok": True, "result": result(value)}, separators=(",", ":")))
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

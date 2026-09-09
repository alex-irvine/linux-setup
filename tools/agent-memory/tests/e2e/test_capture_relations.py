import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent_memory.capture import Outbox, Worker
from agent_memory.index import MemoryIndex
from agent_memory.model import AddRequest, ListQuery
from agent_memory.ollama import OllamaClient
from agent_memory.store import MarkdownStore, MemoryService


@contextmanager
def ollama(responses):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/api/embed":
                assert body["model"] == "fixture-embed"
                payload = {"embeddings": responses["embed"](body["input"])}
            else:
                assert body["model"] == "fixture-review"
                prompt = body["prompt"]
                response = responses["relation"] if '"relation"' in prompt else responses["capture"]
                payload = {"response": response}
            encoded = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


def review(content, supersedes=()):
    return json.dumps({"type": "fact", "scope": "global", "project": None, "content": content,
                       "importance": 0.8, "confidence": 0.9, "tags": ["fixture"],
                       "durability": True, "supersedes": list(supersedes)})


def worker(tmp_path, url, prior_content="Existing public fact."):
    home, vault = tmp_path / "state", tmp_path / "vault"
    service = MemoryService(MarkdownStore(vault, home), MemoryIndex(home / "index.sqlite3"))
    prior = service.add(AddRequest("prior", "fact", "global", prior_content))
    service.ollama = OllamaClient(url, review_model="fixture-review", embed_model="fixture-embed")
    return service, prior, Outbox(home), Worker(service, home)


def enqueue(outbox, identifier="candidate"):
    outbox.enqueue("capture", {"id": identifier, "version": 1, "event": "completed_work", "client": "claude",
                               "source_session": "synthetic", "evidence": {"summary": "Public completed work."}})


def test_capture_relation_decisions_use_real_ollama_and_preserve_contradictions(tmp_path):
    responses = {"capture": review("Candidate public fact."), "relation": json.dumps({"relation": "duplicate"}),
                 "embed": lambda texts: [[1.0, 0.0] for _ in texts]}
    with ollama(responses) as url:
        service, _, outbox, runner = worker(tmp_path / "duplicate", url)
        enqueue(outbox)
        report = runner.run(True)
        assert report["rejected_by_reason"] == ["semantic_duplicate"]
        assert len(service.list(ListQuery())) == 1

        responses["relation"] = json.dumps({"relation": "contradiction"})
        service, _, outbox, runner = worker(tmp_path / "contradiction", url)
        enqueue(outbox)
        assert runner.run(True)["accepted"] == ["candidate"]
        assert len(service.list(ListQuery())) == 2


def test_capture_explicit_supersession_skips_relation_and_updates_prior(tmp_path):
    responses = {"capture": "", "relation": "not json", "embed": lambda texts: [[1.0, 0.0] for _ in texts]}
    with ollama(responses) as url:
        service, prior, outbox, runner = worker(tmp_path, url)
        responses["capture"] = review("Replacement public fact.", [str(prior.id)])
        enqueue(outbox)
        assert runner.run(True)["accepted"] == ["candidate"]
        assert service.get(prior.id).status == "superseded"
        active = service.list(ListQuery())
        assert len(active) == 1 and active[0].supersedes == (str(prior.id),)


@pytest.mark.parametrize("relation", ["not json", json.dumps({"relation": "unknown"})])
def test_capture_degraded_relation_retries_without_canonical_mutation(tmp_path, relation):
    responses = {"capture": review("Candidate public fact."), "relation": relation,
                 "embed": lambda texts: [[1.0, 0.0] for _ in texts]}
    with ollama(responses) as url:
        service, prior, outbox, runner = worker(tmp_path, url)
        enqueue(outbox)
        report = runner.run(True)
        assert report["retrying"] == 1
        assert service.get(prior.id).status == "active"
        assert len(service.list(ListQuery())) == 1
        assert outbox.counts()["ready"] == 1


@pytest.mark.parametrize("vectors", [lambda texts: [], lambda texts: [[1.0, 0.0]], lambda texts: [[1.0], [1.0, 0.0]]])
def test_capture_bad_embedding_batches_retry_without_canonical_mutation(tmp_path, vectors):
    responses = {"capture": review("Candidate public fact."), "relation": json.dumps({"relation": "distinct"}),
                 "embed": vectors}
    with ollama(responses) as url:
        service, prior, outbox, runner = worker(tmp_path, url)
        enqueue(outbox)
        assert runner.run(True)["retrying"] == 1
        assert service.get(prior.id).status == "active"
        assert len(service.list(ListQuery())) == 1

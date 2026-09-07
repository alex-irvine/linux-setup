import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent_memory.ollama import EmbeddingBatch, DegradedStatus, OllamaClient


@contextmanager
def ollama(embed):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            encoded = json.dumps({"embeddings": embed(body["input"])}).encode()
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


def test_search_orders_by_fused_score_and_reuses_valid_embeddings(tmp_path):
    from agent_memory.index import MemoryIndex
    from agent_memory.model import AddRequest, SearchQuery
    from agent_memory.store import MarkdownStore, MemoryService

    home, vault = tmp_path / "state", tmp_path / "vault"
    service = MemoryService(MarkdownStore(vault, home), MemoryIndex(home / "index.sqlite3"))
    lexical = service.add(AddRequest("lexical", "fact", "global", "alpha lexical fixture"))
    semantic = service.add(AddRequest("semantic", "fact", "global", "synthetic semantic fixture", importance=1, confidence=1, pinned=True))
    calls = []
    def embed(texts):
        calls.append(list(texts))
        return EmbeddingBatch([[1.0, 0.0] if "semantic" in text or text == "query" else [0.0, 1.0] for text in texts])
    service.ollama.embed = embed
    result = service.search(SearchQuery("query"))
    assert result.memories[0]["id"] == str(semantic.id)
    assert calls[1] == [lexical.content, semantic.content]
    service.search(SearchQuery("query"))
    assert len(calls) == 3  # Query only on the second search.


def test_search_regenerates_bad_vectors_and_falls_back_when_embedding_is_bad(tmp_path):
    from agent_memory.index import MemoryIndex
    from agent_memory.model import AddRequest, SearchQuery
    from agent_memory.store import MarkdownStore, MemoryService

    home, vault = tmp_path / "state", tmp_path / "vault"
    service = MemoryService(MarkdownStore(vault, home), MemoryIndex(home / "index.sqlite3"))
    record = service.add(AddRequest("fixture", "fact", "global", "vector fixture"))
    service.index.remember_embeddings([record], [[1.0]])
    service.ollama.embed = lambda texts: EmbeddingBatch([[1.0, 0.0] for _ in texts])
    assert service.search(SearchQuery("vector")).semantic_status == "available"
    service.ollama.embed = lambda texts: EmbeddingBatch([])
    assert service.search(SearchQuery("vector")).semantic_status == "unavailable"


def test_ranking_boosts_are_bounded_and_do_not_reorder_rrf_scores(tmp_path):
    from agent_memory.index import MemoryIndex
    from agent_memory.model import AddRequest, SearchQuery, SearchResult
    from agent_memory.store import MarkdownStore, MemoryService

    home, vault = tmp_path / "state", tmp_path / "vault"
    service = MemoryService(MarkdownStore(vault, home), MemoryIndex(home / "index.sqlite3"))
    high = service.add(AddRequest("high", "fact", "global", "first lexical result", importance=0, confidence=0))
    low = service.add(AddRequest("low", "fact", "project", "second lexical result", "fixture", importance=1, confidence=1, pinned=True))
    service.index.set_feedback(str(low.id), 1, 0)
    service.index.search_lexical = lambda query: SearchResult([high.to_dict(), low.to_dict()])
    service.index.candidates = lambda query: [high, low]
    service.ollama.embed = lambda texts: DegradedStatus("synthetic pure-score fixture")

    result = service.search(SearchQuery("fixture", project="fixture"))
    assert [hit["id"] for hit in result.memories] == [str(high.id), str(low.id)]
    contributions = result.memories[1]["explanation"]["boost_contributions"]
    assert {"project_exact", "pinned", "importance", "confidence", "positive_feedback", "recency"} <= contributions.keys()
    assert all(value <= 0.002 for value in contributions.values())
    assert sum(contributions.values()) <= result.memories[1]["explanation"]["boost_cap"]


def test_fused_ranking_is_deterministic_for_lexical_and_semantic_only_hits(tmp_path):
    from agent_memory.index import MemoryIndex
    from agent_memory.model import AddRequest, SearchQuery
    from agent_memory.store import MarkdownStore, MemoryService

    home, vault = tmp_path / "state", tmp_path / "vault"
    service = MemoryService(MarkdownStore(vault, home), MemoryIndex(home / "index.sqlite3"))
    lexical = service.add(AddRequest("lexical", "fact", "global", "query lexical fixture"))
    semantic = service.add(AddRequest("semantic", "fact", "global", "unrelated semantic fixture"))
    service.ollama.embed = lambda texts: EmbeddingBatch([[1.0, 0.0] if text != lexical.content else [0.0, 1.0] for text in texts])
    first = service.search(SearchQuery("query"))
    second = service.search(SearchQuery("query"))
    assert [hit["id"] for hit in first.memories] == [str(lexical.id), str(semantic.id)]
    assert [hit["id"] for hit in second.memories] == [str(lexical.id), str(semantic.id)]
    assert first.memories[1]["semantic_rank"] == 1 and first.memories[1]["lexical_rank"] is None
    assert first.memories[0]["lexical_rank"] == 1


@pytest.mark.parametrize("kind", ["empty", "count", "dimension", "scalar", "nonnumeric", "nonlist", "boolean", "nan", "infinity", "overflow"])
def test_local_ollama_invalid_embedding_batches_fall_back_to_lexical(tmp_path, kind):
    from agent_memory.index import MemoryIndex
    from agent_memory.model import AddRequest, SearchQuery
    from agent_memory.store import MarkdownStore, MemoryService

    home, vault = tmp_path / "state", tmp_path / "vault"
    service = MemoryService(MarkdownStore(vault, home), MemoryIndex(home / "index.sqlite3"))
    record = service.add(AddRequest("fixture", "fact", "global", "lexical fixture"))
    service.add(AddRequest("semantic", "fact", "global", "semantic fixture"))
    def vectors(texts):
        if kind == "empty":
            return []
        if kind == "count":
            return [[1.0, 0.0]]
        if kind == "dimension":
            return [[1.0, 0.0]] if len(texts) == 1 else [[1.0], [1.0, 0.0]]
        if kind == "scalar":
            return [1.0 for _ in texts]
        if kind == "nonnumeric":
            return [["invalid", 0.0] for _ in texts]
        if kind == "nonlist":
            return "invalid"
        if kind == "boolean":
            return [[True, 0.0] for _ in texts]
        if kind == "nan":
            return [[float("nan"), 0.0] for _ in texts]
        if kind == "infinity":
            return [[float("inf"), 0.0] for _ in texts]
        return [[10 ** 400, 0.0] for _ in texts]
    with ollama(vectors) as url:
        service.ollama = OllamaClient(url)
        result = service.search(SearchQuery("lexical"))
    assert result.semantic_status == "unavailable"
    assert [hit["id"] for hit in result.memories] == [str(record.id)]


def test_unavailable_ollama_uses_lexical_fallback(tmp_path):
    from agent_memory.index import MemoryIndex
    from agent_memory.model import AddRequest, SearchQuery
    from agent_memory.store import MarkdownStore, MemoryService

    home, vault = tmp_path / "state", tmp_path / "vault"
    service = MemoryService(MarkdownStore(vault, home), MemoryIndex(home / "index.sqlite3"))
    record = service.add(AddRequest("fixture", "fact", "global", "lexical fixture"))
    service.ollama = OllamaClient("http://127.0.0.1:1", timeout=0.01)
    result = service.search(SearchQuery("lexical"))
    assert result.semantic_status == "unavailable"
    assert [hit["id"] for hit in result.memories] == [str(record.id)]

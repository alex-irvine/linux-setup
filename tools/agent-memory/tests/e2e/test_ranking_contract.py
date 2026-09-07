from agent_memory.ollama import EmbeddingBatch, DegradedStatus


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

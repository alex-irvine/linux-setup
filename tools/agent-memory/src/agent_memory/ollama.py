from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Sequence
from urllib.error import URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]


@dataclass(frozen=True)
class DegradedStatus:
    reason: str


class OllamaClient:
    def __init__(self, url: str | None = None, timeout: float = 2.0) -> None:
        self.url = (url or os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout = timeout

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch | DegradedStatus:
        request = Request(f"{self.url}/api/embed", data=json.dumps({"input": list(texts)}).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
            vectors = payload["embeddings"]
            if len(vectors) != len(texts):
                return DegradedStatus("unexpected embedding count")
            return EmbeddingBatch([[float(value) for value in vector] for vector in vectors])
        except (OSError, URLError, ValueError, KeyError, json.JSONDecodeError) as error:
            return DegradedStatus(str(error))

    def review_capture(self, candidate: dict) -> dict | DegradedStatus:
        request = Request(f"{self.url}/api/generate", data=json.dumps({"stream": False,
            "prompt": "Return strict JSON only with exactly type, scope, project, content, importance, confidence, tags, durability, supersedes. Curate completed-work evidence; never copy transcripts or private data. " + json.dumps(candidate, sort_keys=True)}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                review = json.loads(json.loads(response.read())["response"])
            required = {"type", "scope", "project", "content", "importance", "confidence", "tags", "durability", "supersedes"}
            if set(review) != required:
                return DegradedStatus("invalid capture review")
            return review
        except (OSError, URLError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            return DegradedStatus(str(error))

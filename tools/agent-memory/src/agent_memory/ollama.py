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
            if (not isinstance(vectors, list) or len(vectors) != len(texts)
                    or any(not isinstance(vector, list) or not vector for vector in vectors)
                    or any(not isinstance(value, (int, float)) or isinstance(value, bool)
                           for vector in vectors for value in vector)):
                return DegradedStatus("invalid embedding response")
            return EmbeddingBatch([[float(value) for value in vector] for vector in vectors])
        except (OSError, URLError, TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
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

    def review_relation(self, candidate: str, existing: str) -> str | DegradedStatus:
        request = Request(f"{self.url}/api/generate", data=json.dumps({"stream": False,
            "prompt": "Return strict JSON only: {\"relation\":\"duplicate|contradiction|distinct\"}. "
                      "Decide the factual relation between candidate and existing. "
                      + json.dumps({"candidate": candidate, "existing": existing}, sort_keys=True)}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.loads(json.loads(response.read())["response"])
            if set(result) != {"relation"} or result["relation"] not in {"duplicate", "contradiction", "distinct"}:
                return DegradedStatus("invalid relation review")
            return result["relation"]
        except (OSError, URLError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            return DegradedStatus(str(error))

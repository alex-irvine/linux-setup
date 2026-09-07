from __future__ import annotations

import math


def reciprocal_rank(rank: int) -> float:
    return 1 / (60 + rank)


def cosine(left: list[float], right: list[float]) -> float:
    denominator = math.sqrt(sum(value * value for value in left) * sum(value * value for value in right))
    return sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0.0

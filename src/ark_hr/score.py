"""Job-match maths. The model never auto-rejects, and it never sees the candidate's name."""

from __future__ import annotations

from typing import Any


def score_percent(must: list[dict[str, Any]], nice: list[dict[str, Any]]) -> int | None:
    def average(rows: list[dict[str, Any]]) -> float | None:
        if not rows:
            return None
        weights = {"met": 1.0, "partly": 0.5, "not_met": 0.0}
        total = 0.0
        for row in rows:
            total += weights.get(str(row.get("result") or "not_met"), 0.0)
        return total / len(rows)

    must_avg = average(must)
    nice_avg = average(nice)
    if must_avg is None and nice_avg is None:
        return None
    if must_avg is None:
        return round(100 * nice_avg)
    if nice_avg is None:
        return round(100 * must_avg)
    return round(100 * (0.7 * must_avg + 0.3 * nice_avg))


def normalise_checklist(raw: Any) -> dict[str, list[str]]:
    source = raw if isinstance(raw, dict) else {}

    def lines(key: str) -> list[str]:
        value = source.get(key)
        if not isinstance(value, list):
            return []
        cleaned = []
        for item in value:
            text = item.strip() if isinstance(item, str) else ""
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned

    return {"must": lines("must"), "nice": lines("nice")}


def must_met_label(must: list[dict[str, Any]]) -> str:
    met = sum(1 for row in must if row.get("result") == "met")
    return f"{met} of {len(must)}"

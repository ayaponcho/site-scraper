"""Extraction LLM des points clés d’un article (JSON structuré pour la veille)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

KEY_POINTS_SYSTEM = """Tu es un analyste éditorial pour des posts LinkedIn / X (Twitter).
À partir d’un article (titre + extrait), extrais les points importants au format JSON strict.

Réponds UNIQUEMENT avec un objet JSON de cette forme :
{
  "summary": "résumé en 1-3 phrases",
  "key_points": ["point factuel 1", "point 2", "..."],
  "quotes": ["citation courte éventuelle"],
  "tags": ["tag1", "tag2"],
  "angles": ["angle de post social 1", "angle 2"],
  "why_it_matters": "pourquoi c’est utile pour une audience tech / SaaS / IA"
}

Règles :
- 3 à 8 key_points max, concrets (chiffres, nouveautés, impacts).
- tags en minuscules, sans #.
- Si le texte est pauvre, dis-le dans summary et remplis key_points au mieux.
- Pas de markdown hors JSON.
"""


def _extract_json(content: str) -> dict[str, Any] | None:
    text = (content or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _as_str_list(raw: Any, *, limit: int = 12) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        s = str(item or "").strip()
        if s:
            out.append(s[:500])
        if len(out) >= limit:
            break
    return out


def normalize_key_points(raw: dict[str, Any] | None, *, source: str) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    return {
        "summary": str(data.get("summary") or "").strip()[:2000],
        "key_points": _as_str_list(data.get("key_points"), limit=10),
        "quotes": _as_str_list(data.get("quotes"), limit=6),
        "tags": [t.lower() for t in _as_str_list(data.get("tags"), limit=12)],
        "angles": _as_str_list(data.get("angles"), limit=6),
        "why_it_matters": str(data.get("why_it_matters") or "").strip()[:1500],
        "source": source,
    }


def heuristic_key_points(
    *,
    title: str,
    insights: str,
    url: str,
) -> dict[str, Any]:
    text = (insights or "").strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    points = sentences[:5] if sentences else ([title.strip()] if title.strip() else [])
    return normalize_key_points(
        {
            "summary": (sentences[0] if sentences else title or "Contenu insuffisant pour un résumé.")[:500],
            "key_points": points,
            "quotes": [],
            "tags": [],
            "angles": [
                f"Réagir à : {title.strip()[:120]}" if title.strip() else "Commenter cette actualité",
            ],
            "why_it_matters": "Analyse heuristique — configure OPENAI_API_KEY sur site-scraper pour un JSON LLM plus riche.",
        },
        source="heuristic",
    )


async def _call_openai(user_prompt: str) -> dict[str, Any] | None:
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        return None
    model = (settings.openai_model or "gpt-4o-mini").strip()
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            res = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "temperature": 0.35,
                    "max_tokens": 1800,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": KEY_POINTS_SYSTEM},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            res.raise_for_status()
            data = res.json()
            content = data["choices"][0]["message"]["content"]
            parsed = _extract_json(content)
            if parsed:
                return normalize_key_points(parsed, source="openai")
            return None
    except Exception as exc:
        logger.warning("llm_key_points OpenAI failed: %s", exc)
        return None


def _build_user_prompt(*, title: str, url: str, insights: str, sections: list[dict[str, Any]]) -> str:
    section_bits: list[str] = []
    for row in sections[:12]:
        if not isinstance(row, dict):
            continue
        t = str(row.get("text") or "").strip()
        if t:
            section_bits.append(t[:400])
    body = (insights or "").strip()
    if not body and section_bits:
        body = "\n".join(section_bits)
    body = body[:8000]
    return (
        f"Titre : {title.strip() or '(sans titre)'}\n"
        f"URL : {url.strip()}\n\n"
        f"--- Contenu ---\n{body or '(vide)'}\n"
    )


async def extract_key_points(
    *,
    title: str,
    url: str,
    insights: str,
    sections: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    prompt = _build_user_prompt(
        title=title,
        url=url,
        insights=insights,
        sections=sections or [],
    )
    llm = await _call_openai(prompt)
    if llm:
        return llm
    return heuristic_key_points(title=title, insights=insights, url=url)

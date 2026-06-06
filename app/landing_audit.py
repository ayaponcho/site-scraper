"""Audit critique landing page — marketing growth (LLM + fallback heuristique)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

KIND_LABELS = {
    "evergreen": "Marque evergreen",
    "product": "Produit / SaaS",
    "service": "Prestation / service",
    "event": "Événement",
}

AUDIT_SYSTEM = """Tu es consultant senior en landing pages B2B et marketing growth (LinkedIn, funnel TOFU/MOFU/BOFU).

Mission : produire un audit CRITIQUE et actionnable d'une page web, pour aider à structurer l'offre éditoriale LinkedIn.

Ton : direct, bienveillant, jamais vague. Si le contenu scrape est pauvre (SPA, peu de texte), dis-le clairement et base-toi sur ce qui est disponible + bonnes pratiques du type de page attendu.

JSON strict uniquement :
{
  "verdict": "2-3 phrases — lecture globale honnête",
  "strengths": ["3 à 6 points forts observés ou inférés"],
  "weaknesses": ["3 à 6 faiblesses / risques conversion / clarté"],
  "growth_recommendations": ["4 à 8 actions concrètes priorisées (copy, preuve, CTA, structure, ICP)"],
  "linkedin_angle": "1 paragraphe : comment traduire cette page en ligne éditoriale LinkedIn sur la période",
  "suggested_offer_fields": {
    "label": "nom offre/sujet si pertinent sinon vide",
    "promise": "promesse ICP reformulée si déductible sinon vide",
    "differentiation": "angle différenciant si déductible sinon vide",
    "proofPoints": "preuves manquantes ou à ajouter, séparées par ·"
  }
}

Règles :
- Français
- Pas de CTA générique inventé type « DM MISSION » sauf s'il est explicitement sur la page
- Ne remplis suggested_offer_fields que si tu peux t'appuyer sur le contenu fourni
- weaknesses doit être sincère (pas que du positif)"""


def _field_map(analysis: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in analysis.get("fields") or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").replace("auto_", "")
        val = row.get("value")
        if val is not None and str(val).strip():
            out[key] = str(val).strip()
    return out


def _sections_text(analysis: dict[str, Any], max_sections: int = 12) -> str:
    lines: list[str] = []
    for sec in (analysis.get("sections") or [])[:max_sections]:
        if not isinstance(sec, dict):
            continue
        t = str(sec.get("text") or "").strip()
        if t:
            kind = sec.get("type") or "block"
            lines.append(f"[{kind}] {t[:800]}")
    return "\n".join(lines)


def _build_user_prompt(url: str, kind: str, analysis: dict[str, Any]) -> str:
    kind_label = KIND_LABELS.get(kind, kind)
    fields = _field_map(analysis)
    warnings = analysis.get("warnings") or []
    tags = analysis.get("tags") or []
    sections = _sections_text(analysis)

    parts = [
        f"URL : {url}",
        f"Type d'offre cible (onglet LinkedIn) : {kind_label}",
        f"HTTP status : {analysis.get('http_status', 0)}",
        "",
        "Métadonnées extraites :",
        json.dumps(fields, ensure_ascii=False, indent=2) if fields else "(aucune)",
        "",
        "Avertissements scrape :",
        "\n".join(f"- {w}" for w in warnings) if warnings else "(aucun)",
        "",
        "Sections page :",
        sections if sections else "(aucune section textuelle détectée — probable SPA ou contenu JS)",
        "",
        "Tags :",
        ", ".join(str(t) for t in tags[:15]) if tags else "(aucun)",
    ]
    return "\n".join(parts)


def _extract_json(raw: str) -> dict[str, Any] | None:
    txt = raw.strip()
    candidates = [txt]
    for m in re.findall(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", txt, flags=re.I):
        candidates.append(m)
    start, end = txt.find("{"), txt.rfind("}")
    if start >= 0 and end > start:
        candidates.append(txt[start : end + 1])
    for cand in candidates:
        try:
            parsed = json.loads(cand)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return None


def _normalize_audit(data: dict[str, Any]) -> dict[str, Any]:
    def norm_list(key: str, max_items: int = 8) -> list[str]:
        raw = data.get(key)
        if not isinstance(raw, list):
            return []
        return [str(x).strip() for x in raw if str(x).strip()][:max_items]

    offer_raw = data.get("suggested_offer_fields")
    offer: dict[str, str] = {}
    if isinstance(offer_raw, dict):
        for k in ("label", "promise", "differentiation", "proofPoints"):
            v = str(offer_raw.get(k) or "").strip()
            if v:
                offer[k] = v[:2000]

    return {
        "verdict": str(data.get("verdict") or "").strip()[:2000],
        "strengths": norm_list("strengths"),
        "weaknesses": norm_list("weaknesses"),
        "growth_recommendations": norm_list("growth_recommendations", 10),
        "linkedin_angle": str(data.get("linkedin_angle") or "").strip()[:2000],
        "suggested_offer_fields": offer,
        "source": "openai" if data.get("_source") != "heuristic" else "heuristic",
    }


def _heuristic_audit(url: str, kind: str, analysis: dict[str, Any]) -> dict[str, Any]:
    kind_label = KIND_LABELS.get(kind, kind)
    fields = _field_map(analysis)
    warnings = list(analysis.get("warnings") or [])
    title = fields.get("title", "")
    desc = fields.get("description") or fields.get("insights", "")
    sections = analysis.get("sections") or []

    strengths: list[str] = []
    weaknesses: list[str] = []
    recs: list[str] = []

    if title:
        strengths.append(f"Titre de page identifiable : « {title[:120]} ».")
    if desc:
        strengths.append("Une meta description ou extrait est présent — base pour une promesse.")
    if sections:
        strengths.append(f"{len(sections)} bloc(s) de contenu structuré détecté(s) (titres/listes).")

    if not desc and not sections:
        weaknesses.append(
            "Peu ou pas de texte exploitable (meta, paragraphes) — landing probablement en SPA/JS : "
            "le message offre n'est pas lisible pour un audit automatique."
        )
    if not title or len(title) < 8:
        weaknesses.append("Titre faible ou absent — l'identité de l'offre n'est pas claire en 3 secondes.")
    if "publication" in " ".join(warnings).lower():
        weaknesses.append("Pas de signaux temporels — normal pour une homepage, mais limite pour un événement.")

    recs.extend(
        [
            f"Aligner la page sur le type « {kind_label} » : promesse ICP explicite above the fold.",
            "Ajouter 3 preuves concrètes (chiffres, logos clients, cas d'usage) visibles sans scroll.",
            "Un seul CTA principal répété — éviter la dispersion (demo, contact, newsletter).",
            "Bloc « pour qui / pas pour qui » pour qualifier l'ICP LinkedIn.",
            "Traduire la page en angle éditorial : problème → insight → ouverture (sans pitch agressif).",
        ]
    )

    if "spa" in " ".join(warnings).lower() or (not desc and not sections):
        recs.insert(
            0,
            "Enrichir le HTML statique (SSR ou meta) pour que crawlers et IA lisent promesse et preuves.",
        )

    offer: dict[str, str] = {}
    if kind != "evergreen" and title:
        offer["label"] = title.split("|")[0].strip()[:200]
    if desc:
        offer["promise"] = desc[:500]

    verdict = (
        f"Analyse limitée par le contenu scrape. "
        f"Pour une landing {kind_label}, il manque surtout une promesse et des preuves lisibles machine."
        if not desc and not sections
        else f"Lecture partielle possible — affine la promesse et les preuves pour le positionnement {kind_label}."
    )

    return _normalize_audit(
        {
            "verdict": verdict,
            "strengths": strengths or ["URL accessible — point de départ pour itérer."],
            "weaknesses": weaknesses or ["Audit heuristique — active OPENAI_API_KEY pour une analyse plus fine."],
            "growth_recommendations": recs,
            "linkedin_angle": (
                "Utilise l'onglet Offre pour formaliser une promesse unique dérivée de ta page, "
                "puis décliner en posts TOFU (problème ICP), MOFU (méthode/preuve), BOFU (CTA mesuré)."
            ),
            "suggested_offer_fields": offer,
            "_source": "heuristic",
        }
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
                    "temperature": 0.45,
                    "max_tokens": 2200,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": AUDIT_SYSTEM},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            res.raise_for_status()
            data = res.json()
            content = data["choices"][0]["message"]["content"]
            parsed = _extract_json(content)
            if parsed:
                parsed["_source"] = "openai"
            return parsed
    except Exception as exc:
        logger.warning("landing_audit OpenAI failed: %s", exc)
        return None


async def build_landing_audit(url: str, kind: str, analysis: dict[str, Any]) -> dict[str, Any]:
    user_prompt = _build_user_prompt(url, kind, analysis)
    llm = await _call_openai(user_prompt)
    if llm:
        return _normalize_audit(llm)
    return _heuristic_audit(url, kind, analysis)

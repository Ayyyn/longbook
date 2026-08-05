"""Building a BusinessProfile from the interview and the message sample.

The seed profiles in app/profiles are the floor, not the answer: they carry
sane defaults so a tenant is never left with an empty configuration, and the
Configurator overlays whatever it can actually evidence from the tenant's own
messages. If the agent fails or the sample is too thin to say anything, the
owner still ends up with a working system rather than a failed onboarding —
which matters when this is happening across a table in ten minutes.
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from app.agents import Configurator
from app.models.ingestion import Interaction

PROFILE_DIR = Path(__file__).resolve().parents[1] / "profiles"
SAMPLE_SIZE = 300

# Only keys the Configurator is allowed to decide. Anything else it invents is
# ignored rather than written into the profile that drives every prompt.
PROFILE_KEYS = ("segments", "modules", "vocabulary", "rules")


@lru_cache
def seed_profile(name: str) -> dict[str, Any]:
    path = PROFILE_DIR / f"{name}.yaml"
    if not path.exists():
        path = PROFILE_DIR / "wholesaler.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def seed_for(segments: list[str]) -> dict[str, Any]:
    """Retail only when retail is the whole story — a shop that also wholesales
    needs the wholesaler modules (lots, dispatch) switched on."""
    lowered = {s.strip().lower() for s in segments}
    if lowered == {"retail"}:
        return seed_profile("retail")
    return seed_profile("wholesaler")


def sample_messages(db, tenant_id: uuid.UUID, limit: int = SAMPLE_SIZE) -> list[str]:
    """The most recent messages with actual text in them.

    Recent rather than random: how the business talks today is what the
    extraction prompts have to match.
    """
    rows = db.execute(
        select(Interaction.body)
        .where(
            Interaction.tenant_id == tenant_id,
            Interaction.body.isnot(None),
            Interaction.body != "",
        )
        .order_by(Interaction.occurred_at.desc().nullslast())
        .limit(limit)
    ).scalars().all()
    return [body for body in rows if body and body.strip()]


def _merge(seed: dict[str, Any], decided: dict[str, Any]) -> dict[str, Any]:
    """Seed defaults underneath, agent findings on top, one level deep."""
    merged: dict[str, Any] = {}
    for key in PROFILE_KEYS:
        base = seed.get(key)
        found = decided.get(key)
        if isinstance(base, dict) and isinstance(found, dict):
            merged[key] = {**base, **found}
        elif found not in (None, [], {}):
            merged[key] = found
        else:
            merged[key] = base if base is not None else ({} if key != "segments" else [])
    return merged


def build_profile(
    db, tenant_id: uuid.UUID, interview_text: str, segments: list[str], trace_id: uuid.UUID
) -> dict[str, Any]:
    """Run the Configurator over the sample and return the profile to persist.

    Never raises on agent failure: a tenant with a seed profile can be
    corrected from the dashboard, a tenant with no profile cannot use the
    product at all.
    """
    seed = seed_for(segments)
    sample = sample_messages(db, tenant_id)

    result: dict[str, Any] = {"source": "seed", "confidence": None, "rationale": ""}

    if sample:
        agent = Configurator(db, tenant_id, None)
        try:
            decision = agent.execute(
                {"interview": interview_text, "sample": sample}, trace_id=trace_id
            )
            result = {
                "source": "configurator",
                "confidence": decision.confidence,
                "rationale": decision.rationale,
                **_merge(seed, decision.output),
            }
        except Exception as exc:  # noqa: BLE001 - onboarding must not dead-end
            result["rationale"] = (
                f"Configurator unavailable ({type(exc).__name__}); started from the "
                f"{'retail' if seed is seed_profile('retail') else 'wholesaler'} seed profile."
            )
    else:
        result["rationale"] = "No message sample yet; started from the seed profile."

    for key in PROFILE_KEYS:
        result.setdefault(key, seed.get(key, [] if key == "segments" else {}))

    # The owner ticked these boxes themselves; do not let inference overrule them.
    if segments:
        result["segments"] = segments

    return result

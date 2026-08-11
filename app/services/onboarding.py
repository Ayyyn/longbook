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

# Thresholds the agent may set, and the range a real textile business could
# plausibly occupy. Measured failure: from one ₹96→₹94 haggle it inferred
# `rate_deviation_pct: 2.08`, which would flag almost every order, and from a
# single "will clear by Saturday" it inferred `overdue_days: 7`. A threshold
# derived from one observation is a fact about that observation, not about the
# business.
RULE_BOUNDS: dict[str, tuple[float, float]] = {
    "overdue_days": (15, 120),
    "rate_deviation_pct": (5, 50),
    "low_stock_threshold": (1, 100_000),
    "high_value_amount": (10_000, 10_000_000),
}

# How many supporting observations the agent must cite before its number
# replaces the seed's. Below this the seed wins and the reason is recorded.
MIN_OBSERVATIONS = 3


def clamp_rules(
    seed_rules: dict[str, Any],
    proposed: dict[str, Any],
    evidence: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Accept the agent's thresholds only where they are supported and sane.

    Returns the rules to persist and a note for each one that was rejected, so
    the owner can be told what the system decided to ignore rather than having
    it happen silently.
    """
    evidence = evidence or {}
    rules = dict(seed_rules or {})
    notes: list[str] = []

    for key, value in (proposed or {}).items():
        if key not in RULE_BOUNDS:
            # Not a threshold we govern; pass it through untouched.
            rules[key] = value
            continue

        try:
            number = float(value)
        except (TypeError, ValueError):
            notes.append(f"{key}: '{value}' is not a number, kept {rules.get(key)}")
            continue

        support = evidence.get(key)
        try:
            support = int(support)
        except (TypeError, ValueError):
            support = 0

        if support < MIN_OBSERVATIONS:
            notes.append(
                f"{key}: {number:g} inferred from {support} observation(s), "
                f"kept the seed's {rules.get(key)}"
            )
            continue

        low, high = RULE_BOUNDS[key]
        if not low <= number <= high:
            clamped = min(max(number, low), high)
            notes.append(f"{key}: {number:g} is outside {low:g}-{high:g}, clamped to {clamped:g}")
            number = clamped

        rules[key] = int(number) if float(number).is_integer() else number

    return rules, notes


@lru_cache
def seed_profile(name: str = "universal") -> dict[str, Any]:
    path = PROFILE_DIR / f"{name}.yaml"
    if not path.exists():
        path = PROFILE_DIR / "universal.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def seed_for(segments: list[str]) -> dict[str, Any]:
    """One seed, whatever the trade.

    There used to be a wholesaler seed and a retail seed, both written for
    fabric. They were not a head start — the Configurator derives vocabulary
    and rate basis from the owner's own messages perfectly well, and every
    trade-specific default it failed to override shipped as a wrong answer to
    a business in a different trade.

    `segments` is kept because the caller has it and the Configurator reads
    it as evidence; it no longer selects a file.
    """
    seed = dict(seed_profile("universal"))
    seed["segments"] = [s.strip().lower() for s in segments if s and s.strip()]
    return seed


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
        if key == "rules" and isinstance(base, dict):
            # Thresholds are governed rather than merged; see clamp_rules.
            continue
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
            merged = _merge(seed, decision.output)
            rules, notes = clamp_rules(
                seed.get("rules", {}),
                decision.output.get("rules", {}),
                decision.output.get("rules_evidence", {}),
            )
            rationale = decision.rationale
            if notes:
                rationale = f"{rationale} Adjusted: {'; '.join(notes)}."
            result = {
                "source": "configurator",
                "confidence": decision.confidence,
                "rationale": rationale,
                "rule_notes": notes,
                **merged,
                "rules": rules,
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

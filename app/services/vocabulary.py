"""What this business calls things.

The schema is neutral — `Item`, `Batch`, a unit string. What a business calls
those is display, and it differs completely by trade: a fabric wholesaler says
"quality", a machinery dealer says "model", a chemical distributor says
"grade", a garment retailer says "style". Getting it wrong is not cosmetic. An
owner who is asked to confirm the "quality" of a bearing concludes the system
does not understand their business, and they are right.

All of it comes from `BusinessProfile.vocabulary`, which the Configurator
writes from evidence in the owner's own messages. Nothing here is a textile
default; the fallbacks are the generic words, which are correct for any trade
and merely bland for a specific one.
"""

from __future__ import annotations

from typing import Any

# The neutral words. Used when a profile has not said otherwise — never a
# trade's vocabulary, because being bland is recoverable and being wrong is
# not.
DEFAULTS = {
    "item_singular": "item",
    "item_plural": "items",
    "batch_singular": "batch",
    "batch_plural": "batches",
    "party_singular": "party",
    "party_plural": "parties",
    "rate_basis": "per unit",
    "unit_default": "",
}


def _profile_dict(profile: Any) -> dict:
    if profile is None:
        return {}
    raw = getattr(profile, "vocabulary", None)
    return raw if isinstance(raw, dict) else {}


def labels(profile: Any) -> dict[str, str]:
    """Every display label this business uses, resolved once.

    Returned as a flat dict so the API can hand it to the UI and the UI can
    stop guessing. `item_label` is what a fabric trader reads as "Quality".
    """
    vocab = _profile_dict(profile)

    item = (
        vocab.get("item_term")
        or vocab.get("quality_term")          # what earlier profiles wrote
        or DEFAULTS["item_singular"]
    )
    batch = vocab.get("batch_term") or vocab.get("lot_term") or DEFAULTS["batch_singular"]
    party = vocab.get("party_terms") or []
    party_singular = party[0] if isinstance(party, list) and party else DEFAULTS[
        "party_singular"
    ]

    units = vocab.get("quantity_units") or []
    return {
        "item": item,
        "item_plural": vocab.get("item_plural") or _plural(item),
        "batch": batch,
        "batch_plural": vocab.get("batch_plural") or _plural(batch),
        "party": party_singular,
        "party_plural": _plural(party_singular),
        "rate_basis": (vocab.get("rate_basis") or DEFAULTS["rate_basis"]).replace(
            "_", " "
        ),
        "default_unit": units[0] if units else "",
        "units": units,
    }


def _plural(word: str) -> str:
    """Good enough for the handful of words that reach it."""
    if not word:
        return word
    if word.endswith(("s", "x", "ch", "sh")):
        return word + "es"
    if word.endswith("y") and word[-2:-1] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


def default_unit(profile: Any) -> str | None:
    """The unit this business quotes in, or None.

    None rather than a guess. A hardcoded "meter" is how a machinery dealer
    ends up with metres of bearings on their order lines.
    """
    units = _profile_dict(profile).get("quantity_units") or []
    return units[0] if units else None

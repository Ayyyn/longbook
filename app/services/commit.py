"""Commit / review-queue boundary.

Single place where an agent decision becomes a business record. Nothing else
in the codebase should write to order/payment/party tables from extraction.
"""

from __future__ import annotations

from typing import Any


def commit_record(db, state: dict[str, Any]) -> dict[str, Any]:
    """TODO: map extraction fields onto Order/Payment/Dispatch and insert."""
    raise NotImplementedError("build agent: implement per record_type")


def queue_for_review(db, state: dict[str, Any]) -> dict[str, Any]:
    """TODO: persist an Extraction row with status='needs_review'."""
    raise NotImplementedError("build agent: implement review queue write")


def accept_correction(db, extraction_id, corrected: dict[str, Any]) -> None:
    """Owner corrected a queued item. Commit it AND append the corrected pair
    to BusinessProfile.examples so the tenant's extraction improves."""
    raise NotImplementedError("build agent: implement correction harvesting")

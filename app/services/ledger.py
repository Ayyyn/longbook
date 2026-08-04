"""Deterministic ledger maths. No model calls in here — these numbers must be
reproducible and explainable to an owner who will check them against Tally."""

from __future__ import annotations

from datetime import date


def ageing_buckets(db, tenant_id, as_of: date) -> dict[str, float]:
    """0-30 / 31-45 / 46-60 / 60+ outstanding, per the profile's overdue_days."""
    raise NotImplementedError


def overdue_crossings(db, tenant_id, as_of: date, overdue_days: int) -> list[dict]:
    """Parties that crossed the threshold since the last run — the alert that
    makes the daily digest worth opening."""
    raise NotImplementedError


def payment_trend(db, tenant_id, lookback_days: int = 180) -> list[dict]:
    """Parties whose average days-to-pay is deteriorating."""
    raise NotImplementedError

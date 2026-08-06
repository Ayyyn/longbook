"""Export agent runs and API usage as CSV.

Submission evidence for the XPRIZE entry. It has to work on 15 Aug on whatever
the deployed database looks like then, so it depends on nothing but the models
and the standard library, takes no arguments it cannot default, and never
fails on a tenant with no data.

    PYTHONPATH=. python scripts/export_logs.py --out var/export
    PYTHONPATH=. python scripts/export_logs.py --tenant <uuid> --days 30

Writes three files:
    agent_runs.csv    one row per agent decision, the raw evidence
    agent_daily.csv   per agent per day: runs, overrides, latency, cost
    api_usage.csv     per day: tokens, cost, records committed
"""

from __future__ import annotations

import argparse
import csv
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import Integer, func, select

from app.db import admin_session
from app.models.ingestion import Extraction
from app.models.observability import AgentRun
from app.models.tenant import Tenant

RUN_COLUMNS = [
    "tenant_id", "business_name", "run_id", "trace_id", "created_at",
    "agent", "model", "prompt_version", "confidence", "outcome",
    "latency_ms", "input_tokens", "output_tokens", "cost_usd",
    "human_override", "reviewed_at", "rationale", "error", "input_hash",
]


def _rows_to_csv(path: Path, header: list[str], rows) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def _clean(value) -> str:
    """CSV should survive a spreadsheet: no newlines, no None."""
    if value is None:
        return ""
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def export(out_dir: Path, tenant_id: uuid.UUID | None, days: int | None) -> dict[str, int]:
    since = datetime.utcnow() - timedelta(days=days) if days else None
    written: dict[str, int] = {}

    with admin_session() as db:
        names = dict(db.execute(select(Tenant.id, Tenant.business_name)).all())

        where = []
        if tenant_id:
            where.append(AgentRun.tenant_id == tenant_id)
        if since:
            where.append(AgentRun.created_at >= since)

        runs = db.execute(
            select(AgentRun).where(*where).order_by(AgentRun.created_at.asc())
        ).scalars().all()

        written["agent_runs.csv"] = _rows_to_csv(
            out_dir / "agent_runs.csv",
            RUN_COLUMNS,
            (
                [
                    _clean(run.tenant_id),
                    _clean(names.get(run.tenant_id)),
                    _clean(run.id),
                    _clean(run.trace_id),
                    _clean(run.created_at),
                    _clean(run.agent),
                    _clean(run.model),
                    _clean(run.prompt_version),
                    _clean(run.confidence),
                    _clean(run.outcome),
                    _clean(run.latency_ms),
                    _clean(run.input_tokens),
                    _clean(run.output_tokens),
                    _clean(run.cost_usd),
                    "true" if run.human_override else "false",
                    _clean(run.reviewed_at),
                    _clean(run.rationale)[:500],
                    _clean(run.error)[:500],
                    _clean(run.input_hash),
                ]
                for run in runs
            ),
        )

        day = func.date(AgentRun.created_at)
        daily = db.execute(
            select(
                AgentRun.tenant_id,
                day.label("day"),
                AgentRun.agent,
                func.count(),
                func.sum(func.cast(AgentRun.outcome == "ok", Integer)),
                func.sum(func.cast(AgentRun.outcome == "error", Integer)),
                func.sum(func.cast(AgentRun.human_override, Integer)),
                func.avg(AgentRun.confidence),
                func.avg(AgentRun.latency_ms),
                func.coalesce(func.sum(AgentRun.input_tokens), 0),
                func.coalesce(func.sum(AgentRun.output_tokens), 0),
                func.coalesce(func.sum(AgentRun.cost_usd), 0),
            )
            .where(*where)
            .group_by(AgentRun.tenant_id, day, AgentRun.agent)
            .order_by(day, AgentRun.agent)
        ).all()

        written["agent_daily.csv"] = _rows_to_csv(
            out_dir / "agent_daily.csv",
            ["tenant_id", "business_name", "day", "agent", "runs", "ok", "errors",
             "overrides", "override_rate", "avg_confidence", "avg_latency_ms",
             "input_tokens", "output_tokens", "cost_usd"],
            (
                [
                    _clean(tid), _clean(names.get(tid)), _clean(d), _clean(agent),
                    count, int(ok or 0), int(errors or 0), int(overrides or 0),
                    round(int(overrides or 0) / count, 4) if count else 0,
                    round(float(conf), 3) if conf is not None else "",
                    int(latency) if latency is not None else "",
                    int(tokens_in or 0), int(tokens_out or 0), round(float(cost or 0), 6),
                ]
                for (tid, d, agent, count, ok, errors, overrides, conf, latency,
                     tokens_in, tokens_out, cost) in daily
            ),
        )

        # API usage rolled up per day, alongside what the system actually
        # produced that day — tokens spent are only meaningful next to records
        # committed.
        extraction_day = func.date(Extraction.created_at)
        ex_where = []
        if tenant_id:
            ex_where.append(Extraction.tenant_id == tenant_id)
        if since:
            ex_where.append(Extraction.created_at >= since)

        committed = dict(
            db.execute(
                select(extraction_day, func.count())
                .where(*ex_where, Extraction.status.in_(("auto_committed", "accepted",
                                                         "corrected")))
                .group_by(extraction_day)
            ).all()
        )
        reviewed = dict(
            db.execute(
                select(extraction_day, func.count())
                .where(*ex_where, Extraction.status == "needs_review")
                .group_by(extraction_day)
            ).all()
        )

        usage = db.execute(
            select(
                day.label("day"),
                func.count(),
                func.coalesce(func.sum(AgentRun.input_tokens), 0),
                func.coalesce(func.sum(AgentRun.output_tokens), 0),
                func.coalesce(func.sum(AgentRun.cost_usd), 0),
                func.sum(func.cast(AgentRun.human_override, Integer)),
            )
            .where(*where)
            .group_by(day)
            .order_by(day)
        ).all()

        written["api_usage.csv"] = _rows_to_csv(
            out_dir / "api_usage.csv",
            ["day", "agent_runs", "input_tokens", "output_tokens", "cost_usd",
             "records_committed", "records_queued", "human_overrides"],
            (
                [
                    _clean(d), count, int(tokens_in or 0), int(tokens_out or 0),
                    round(float(cost or 0), 6),
                    committed.get(d, 0), reviewed.get(d, 0), int(overrides or 0),
                ]
                for (d, count, tokens_in, tokens_out, cost, overrides) in usage
            ),
        )

    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="var/export", help="output directory")
    parser.add_argument("--tenant", help="limit to one tenant id")
    parser.add_argument("--days", type=int, help="limit to the last N days")
    args = parser.parse_args()

    tenant_id = uuid.UUID(args.tenant) if args.tenant else None
    out_dir = Path(args.out)

    written = export(out_dir, tenant_id, args.days)
    for name, count in written.items():
        print(f"{out_dir / name}: {count} rows")

    if not any(written.values()):
        print("No agent runs matched — nothing to submit yet.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

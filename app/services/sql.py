"""Query helpers for the mistakes this codebase keeps making.

Not a utilities drawer. Each thing here exists because the naive version has
already shipped a silent wrong answer at least once.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, Select, or_


def not_in_subquery(column: ColumnElement, subquery: Select) -> ColumnElement:
    """`column NOT IN (subquery)` that cannot be poisoned by a NULL.

    SQL's NOT IN is three-valued: if the subquery yields even one NULL, the
    predicate evaluates to NULL for *every* row and the query returns nothing
    at all. Not fewer rows — none. It looks exactly like "there is no such
    data", which is the worst possible failure for a question like "which
    orders have not been dispatched".

    This has now bitten three times in this project: the backfill, the chat
    retrieval, and the exception scan. So the safe form is the only form
    available: the subquery is wrapped to drop NULLs by construction, and the
    NULL-safe `IS NOT NULL` guard is not something a caller can forget.

    Pass the subquery selecting exactly one column.
    """
    inner = subquery.subquery()
    target = list(inner.c)[0]
    return column.notin_(
        # The filter lives here rather than at every call site, which is the
        # entire point — three call sites, three chances to leave it out.
        Select(target).select_from(inner).where(target.isnot(None))
    )


def not_in_values(column: ColumnElement, values: list) -> ColumnElement:
    """`column NOT IN (values)` that keeps rows where the column is NULL.

    The other half of the same trap, on the column rather than the subquery:
    `status NOT IN ('closed')` drops rows whose status is NULL, even though a
    NULL status is emphatically not 'closed'. Almost every business use of
    NOT IN means "is not one of these, including if it is not set".
    """
    cleaned = [v for v in values if v is not None]
    if not cleaned:
        return column.is_not(None) | column.is_(None)  # always true
    return or_(column.is_(None), column.notin_(cleaned))

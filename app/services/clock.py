"""What "today" means, in one place.

Every timestamp column in this database is written with `datetime.utcnow()`.
Every business question is asked in Indian time. `date.today()` is neither —
it is whatever the server's clock says, which on Cloud Run is UTC and on a
developer's laptop is not.

That mismatch already shipped a bug: Today compared `date.today()` against
`created_at` and reported zero agent decisions every morning between midnight
and 05:30 IST. It was invisible for weeks because nobody looks at the app at
2am, and it was only caught when a test run happened to cross midnight.

So: one definition of the business day, used everywhere. Comparisons against
a Date column use `business_today()`. Comparisons against a timestamp column
use `business_day_bounds()`, which returns the UTC instants that bracket the
Indian day — a range, so the query stays on the index rather than wrapping the
column in a function.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

# India-only product. A fixed offset rather than a tz database: IST has never
# had daylight saving, and pulling in zoneinfo for one constant would be
# ceremony without benefit.
IST_OFFSET = timedelta(hours=5, minutes=30)


def business_now() -> datetime:
    """Wall-clock time where the customer is."""
    return datetime.utcnow() + IST_OFFSET


def business_today() -> date:
    """Today's date where the customer is.

    Use for anything compared against a Date column — invoice dates, due
    dates, order dates. Those are calendar dates, not instants.
    """
    return business_now().date()


def business_day_bounds(day: date | None = None) -> tuple[datetime, datetime]:
    """The UTC instants [start, end) bracketing an Indian calendar day.

    Use for anything compared against a timestamp column. Comparing
    `func.date(created_at) == business_today()` would be both wrong (it dates
    a UTC instant as if it were local) and slow (no index).
    """
    day = day or business_today()
    start = datetime.combine(day, time.min) - IST_OFFSET
    return start, start + timedelta(days=1)

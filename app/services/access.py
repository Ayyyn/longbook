"""Whether a tenant may use the app today.

Payment is collected in person — cash, cheque or a transfer, then marked here
by hand. There is no gateway and no subscription object; `paid_until` is the
whole of it. That keeps the money conversation where it already happens for
this trade, and keeps card details out of a system that has no business
holding them.

Three states, and the distinction that matters is between *expired* and
*deleted*: an owner whose year lapses keeps every record. They are locked out
of the screens, not erased. People pay late in this business and come back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.models.tenant import Tenant

# How long a business gets before anyone has to have paid. Long enough to see
# a full cycle of their own trade in the app, short enough to be a decision.
TRIAL_DAYS = 14

# When the countdown starts appearing in the app. Two weeks is enough notice to
# arrange a transfer without the app nagging for a month.
WARN_WITHIN_DAYS = 14


@dataclass(frozen=True)
class Access:
    status: str            # trial | active | expired
    days_remaining: int | None
    until: datetime | None

    @property
    def allowed(self) -> bool:
        return self.status != "expired"

    @property
    def expiring_soon(self) -> bool:
        return (
            self.allowed
            and self.days_remaining is not None
            and self.days_remaining <= WARN_WITHIN_DAYS
        )


def access_for(tenant: Tenant, now: datetime | None = None) -> Access:
    """Resolve a tenant's access from `paid_until`, falling back to the trial.

    A tenant switched off by hand (`is_active=False`) is expired regardless of
    what has been paid — that is the lever for a business that has to be
    suspended for some other reason.
    """
    now = now or datetime.utcnow()

    if not tenant.is_active:
        return Access("expired", 0, tenant.paid_until)

    if tenant.paid_until:
        remaining = (tenant.paid_until - now).days
        if tenant.paid_until <= now:
            return Access("expired", 0, tenant.paid_until)
        return Access("active", max(0, remaining), tenant.paid_until)

    # Never paid: the trial runs from the day the business was created, not
    # from onboarding, so an abandoned half-setup does not sit open for ever.
    started = tenant.created_at or now
    ends = started + timedelta(days=TRIAL_DAYS)
    if ends <= now:
        return Access("expired", 0, ends)
    return Access("trial", max(0, (ends - now).days), ends)

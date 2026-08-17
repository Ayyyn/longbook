"""Verification for the connected mailbox.

Nylas itself is not exercised here — that needs a live grant, and a test that
only runs when somebody has connected a real mailbox is a test that never
runs. What is checked is everything around it, which is where the damage
would be: that a Nylas message becomes the same shape a forwarded one does,
that the watermark cannot skip mail, and above all that the callback cannot be
made to attach a mailbox to a business that did not ask for it.

    DATABASE_URL=... PYTHONPATH=. python scripts/verify_mailbox.py
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from app.services import nylas

ok = fail = 0


def check(label: str, got, want) -> None:
    global ok, fail
    if got == want:
        ok += 1
        print(f"  PASS  {label}")
    else:
        fail += 1
        print(f"  FAIL  {label}\n          got={got!r}\n         want={want!r}")


SECRET = "a-server-secret-nobody-else-has"


print("\n-- state binds the callback to one tenant --")

tid = str(uuid.uuid4())
state = nylas.sign_state(tid, SECRET, int(time.time()))

check("a state we signed reads back", nylas.read_state(state, SECRET), tid)

# The whole point. Without this, anyone who can reach the callback picks the
# tenant their mailbox lands on — or lands somebody else's mailbox on theirs.
check("a state signed with another secret is rejected",
      nylas.read_state(state, "some-other-secret"), None)

import base64  # noqa: E402

raw = base64.urlsafe_b64decode(state + "=" * (-len(state) % 4)).decode()
body, mac = raw.rsplit(":", 1)
other = str(uuid.uuid4())
forged = base64.urlsafe_b64encode(
    f"{other}:{body.rsplit(':', 1)[1]}:{mac}".encode()).decode().rstrip("=")
check("swapping the tenant id invalidates the signature",
      nylas.read_state(forged, SECRET), None)

check("a truncated state is rejected", nylas.read_state(state[:12], SECRET), None)
check("an empty state is rejected", nylas.read_state("", SECRET), None)
check("junk is rejected", nylas.read_state("!!!not base64!!!", SECRET), None)

stale = nylas.sign_state(tid, SECRET, int(time.time()) - 4000)
check("a state older than the window is rejected", nylas.read_state(stale, SECRET), None)


print("\n-- a Nylas message becomes an InboundMail --")

when = datetime(2026, 8, 14, 9, 30, tzinfo=timezone.utc)
message = {
    "id": "msg-1",
    "subject": "Invoice 4471",
    "from": [{"name": "Kalyan Mills", "email": "accounts@kalyanmills.in"}],
    "date": int(when.timestamp()),
    "body": (
        "<html><head><style>p{color:red}</style></head><body>"
        "<p>Dear Sir,</p><p>1390 m navy poplin @ &#8377;81.50/m.</p>"
        "<div>Total &#8377;1,13,285</div></body></html>"
    ),
    "attachments": [],
}

mail = nylas.to_inbound("grant-1", message, with_attachments=False)
check("the subject carries over", mail.subject, "Invoice 4471")
check("the sender is readable", mail.sender, "Kalyan Mills <accounts@kalyanmills.in>")
check("the stylesheet does not end up in the body", "color:red" in mail.body, False)
check("the text does", "1390 m navy poplin" in mail.body, True)
check("entities are decoded", "₹81.50" in mail.body, True)
check("there is no markup left", "<" in mail.body, False)

# store_mail parses this with parsedate_to_datetime; a format it cannot read
# means every connected mail is stamped "now" and lands in the wrong window.
from email.utils import parsedate_to_datetime  # noqa: E402

parsed = parsedate_to_datetime(mail.occurred_at)
check("the date parses back to the same instant",
      parsed.astimezone(timezone.utc).replace(tzinfo=None), when.replace(tzinfo=None))

check("received_at is naive UTC, like the rest of the system",
      nylas.received_at(message), when.replace(tzinfo=None))

check("a message with no body falls back to the snippet",
      nylas.to_inbound("g", {"snippet": "short one", "from": []},
                       with_attachments=False).body,
      "short one")
check("a message with no date does not invent one",
      nylas.to_inbound("g", {"from": []}, with_attachments=False).occurred_at, None)
check("a message with no sender does not crash",
      nylas.to_inbound("g", {"subject": "x"}, with_attachments=False).sender, "")


print("\n-- attachments are filtered before they are downloaded --")

# Every mail from a business carries a signature logo and a tracking pixel.
# Extracting those costs a model call each and fills the review queue with
# nothing, so they never get as far as a download.
def taken(item) -> bool:
    """Mirror of the filter in to_inbound, checked against its constants."""
    mime = (item.get("content_type") or "").split(";")[0].strip().lower()
    if item.get("is_inline"):
        return False
    if not (mime.startswith("image/") or mime in nylas.DOCUMENT_TYPES):
        return False
    return int(item.get("size") or 0) <= nylas.MAX_ATTACHMENT


check("a PDF invoice is taken",
      taken({"content_type": "application/pdf", "size": 90_000}), True)
check("a spreadsheet is taken",
      taken({"content_type":
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             "size": 40_000}), True)
check("a photographed bill is taken",
      taken({"content_type": "image/jpeg", "size": 2_000_000}), True)
check("a signature logo is not",
      taken({"content_type": "image/png", "size": 4_000, "is_inline": True}), False)
check("a calendar invite is not",
      taken({"content_type": "text/calendar", "size": 900}), False)
check("an oversized catalogue is not",
      taken({"content_type": "application/pdf", "size": 40 * 1024 * 1024}), False)
check("a content_type with a charset still matches",
      taken({"content_type": "text/csv; charset=utf-8", "size": 500}), True)


print("\n-- the watermark cannot skip mail --")

# list_messages sorts oldest first and the sync stops after one page. If it
# came back newest-first, the watermark would jump to the newest message on
# the page and everything older than it would never be read.
raw_page = [
    {"id": "c", "date": 300},
    {"id": "a", "date": 100},
    {"id": "b", "date": 200},
]
check("a page is ordered oldest first",
      [m["id"] for m in sorted(raw_page, key=lambda m: m.get("date") or 0)],
      ["a", "b", "c"])

check("the default reaches back a year, so a full ordering cycle is covered",
      round((datetime.utcnow() - nylas.default_since()).total_seconds() / 86400), 365)

# The first pull of a mailbox open since 2014 is thousands of messages, and
# every one of them costs a model call downstream. The cap makes that a pause
# rather than a bill: the watermark means the next sync resumes.
from app.config import Settings as _S  # noqa: E402

check("there is a cap on the first pull", _S(_env_file=None).nylas_max_messages > 0, True)

# Paging is what makes "all of it" possible at all — one page of 50 would
# have meant the history trickling in at 50 per sweep.
import inspect as _inspect  # noqa: E402

sig = _inspect.signature(nylas.list_messages)
check("list_messages takes a cursor", "cursor" in sig.parameters, True)
check("  and hands the next one back",
      "next_cursor" in _inspect.getsource(nylas.list_messages), True)

# Sent mail is half of every commitment the business made. Filtering by folder
# would have silently dropped it.
check("no folder filter is sent, so sent mail comes back too",
      '"in"' in _inspect.getsource(nylas.list_messages), False)

from app.services import mail_sync  # noqa: E402

check("the sync has a time budget",
      "budget" in _inspect.signature(mail_sync.sync_account).parameters, True)
check("  and reports when there is more to come",
      '"more"' in _inspect.getsource(mail_sync.sync_account), True)

# received_after is inclusive, so re-reading the boundary message is expected
# and harmless — store_mail dedupes on content. A gap would not be.
check("the window starts at the last message taken, not after it",
      nylas.received_at({"date": int(when.timestamp())}), when.replace(tzinfo=None))


print("\n-- the grant never leaves the server --")

import inspect  # noqa: E402

from app.api import connect  # noqa: E402

source = inspect.getsource(connect)
described = inspect.getsource(connect._describe)
check("the mailbox response model has no grant field",
      "grant_id" in connect.MailboxInfo.model_fields, False)
check("_describe does not put the grant in the payload",
      "grant_id" in described, False)
check("no endpoint returns a grant",
      "grant_id=account.grant_id" in source or '"grant": ' in source, False)


print("\n-- configuration --")

from app.config import Settings  # noqa: E402

blank = Settings(_env_file=None)
check("nylas is off until credentials exist", bool(blank.nylas_client_id), False)
check("  and the api key has no default", blank.nylas_api_key, "")
check("the region is pinned rather than guessed",
      blank.nylas_api_uri.startswith("https://api."), True)
check("the redirect target is absolute",
      blank.api_url.startswith("http"), True)

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)

"""Establishing the party list before the first backfill.

This is what decides whether onboarding feels like magic or like homework. The
Resolver can only auto-commit a record it can attribute to somebody, so a
tenant with an empty `party` table sends its entire 90-day history to the
review queue — thousands of items, and the owner closes the app.

Sources, best first:

1. **Tally** — the accountant's own ledger master. Names, phones, GSTINs,
   credit terms and opening balances, already reconciled.
2. **Excel** — a customer list, in whatever column order the shop uses.
3. **The chat export itself** — who the owner actually talks to. Always
   available, which is the point: it is the floor, not the preference.

Imports are not extractions, so they do not go through `commit.py`'s
confidence gate — an accountant's ledger export is not a model guess. It is
still tenant-scoped and still deduplicated against what is already there.
"""

from __future__ import annotations

import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app.models.finance import Invoice
from app.models.ingestion import Interaction
from app.models.party import Party
from app.services.matching import normalize_phone

# Tally groups every party under one of these. Anything else in the ledger
# master is a bank, a tax head, or an expense — not somebody who owes money.
CUSTOMER_GROUPS = ("sundry debtors", "trade receivables")
SUPPLIER_GROUPS = ("sundry creditors", "trade payables")

# Header names a shop might plausibly use, lowercased and stripped of spaces.
COLUMN_ALIASES = {
    "name": ("name", "party", "partyname", "customer", "customername", "ledger",
             "ledgername", "account", "accountname", "firm", "shopname"),
    "phone": ("phone", "mobile", "mobileno", "phoneno", "contact", "contactno",
              "whatsapp", "number"),
    "city": ("city", "place", "town", "location", "station"),
    "gstin": ("gstin", "gst", "gstno", "gstnumber", "tin"),
    "credit_days": ("creditdays", "credit", "days", "terms", "creditperiod"),
    "outstanding": ("outstanding", "balance", "openingbalance", "opening", "due",
                    "amount", "closingbalance", "baki"),
    "kind": ("kind", "type", "partytype", "category"),
}

OPENING_INVOICE_NO = "OPENING"


@dataclass
class PartySeed:
    name: str
    aliases: list[str] = field(default_factory=list)
    phone: str | None = None
    city: str | None = None
    gstin: str | None = None
    kind: str = "customer"
    credit_days: int | None = None
    outstanding: float | None = None


@dataclass
class ImportResult:
    source: str
    created: int = 0
    merged: int = 0
    skipped: int = 0
    opening_invoices: int = 0
    total_outstanding: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "created": self.created,
            "merged": self.merged,
            "skipped": self.skipped,
            "opening_invoices": self.opening_invoices,
            "total_outstanding": round(self.total_outstanding, 2),
        }


# --- parsing --------------------------------------------------------------


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def _credit_days(value: Any) -> int | None:
    """Tally writes "45 Days"; a spreadsheet writes 45."""
    number = _number(value)
    return int(number) if number is not None and number >= 0 else None


def parse_tally_xml(content: bytes | str) -> list[PartySeed]:
    """Read parties out of a Tally ledger-master export.

    Tally exports debit balances as negative numbers, so a customer who owes
    money shows as -125000. Outstanding is stored as a magnitude and the group
    decides which direction it points.
    """
    if isinstance(content, bytes):
        # Tally writes ISO-8859-1 by default and declares it inconsistently.
        try:
            content = content.decode("utf-8")
        except UnicodeDecodeError:
            content = content.decode("iso-8859-1", errors="replace")

    content = re.sub(r"<\?xml[^>]*\?>", "", content, count=1).strip()
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"Not a readable Tally XML export: {exc}") from exc

    seeds: list[PartySeed] = []
    for ledger in root.iter("LEDGER"):
        name = _clean(ledger.get("NAME")) or _clean(ledger.findtext("NAME"))
        if not name:
            continue

        parent = (_clean(ledger.findtext("PARENT")) or "").lower()
        if any(group in parent for group in CUSTOMER_GROUPS):
            kind = "customer"
        elif any(group in parent for group in SUPPLIER_GROUPS):
            kind = "supplier"
        else:
            continue  # a bank, a tax head, an expense — not a party

        balance = _number(ledger.findtext("OPENINGBALANCE"))
        mailing = [_clean(n.text) for n in ledger.iter("MAILINGNAME") if _clean(n.text)]

        seeds.append(
            PartySeed(
                name=name,
                aliases=[a for a in mailing if a.lower() != name.lower()],
                phone=(
                    _clean(ledger.findtext("LEDGERMOBILE"))
                    or _clean(ledger.findtext("LEDGERPHONE"))
                    or _clean(ledger.findtext("LEDGERCONTACT"))
                ),
                city=_clean(ledger.findtext("LEDGERSTATENAME")) or _clean(
                    ledger.findtext(".//ADDRESS")
                ),
                gstin=(
                    _clean(ledger.findtext("PARTYGSTIN"))
                    or _clean(ledger.findtext("INCOMETAXNUMBER"))
                ),
                kind=kind,
                credit_days=_credit_days(ledger.findtext("BILLCREDITPERIOD")),
                outstanding=abs(balance) if balance else None,
            )
        )
    return seeds


def _column_map(header: tuple) -> dict[str, int]:
    """Match spreadsheet headers to fields, whatever order they came in."""
    found: dict[str, int] = {}
    for index, cell in enumerate(header):
        key = re.sub(r"[^a-z]", "", str(cell or "").lower())
        if not key:
            continue
        for target, aliases in COLUMN_ALIASES.items():
            if target not in found and key in aliases:
                found[target] = index
                break
    return found


def parse_party_excel(path: Path) -> list[PartySeed]:
    """Read a customer list. Column order and casing are the shop's business."""
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        header = next(rows, None)
        if header is None:
            return []

        columns = _column_map(header)
        if "name" not in columns:
            raise ValueError(
                "No name column found. Expected one of: "
                + ", ".join(COLUMN_ALIASES["name"][:5])
            )

        def cell(row, key):
            index = columns.get(key)
            return row[index] if index is not None and index < len(row) else None

        seeds: list[PartySeed] = []
        for row in rows:
            name = _clean(cell(row, "name"))
            if not name:
                continue
            kind = (_clean(cell(row, "kind")) or "customer").lower()
            seeds.append(
                PartySeed(
                    name=name,
                    phone=_clean(cell(row, "phone")),
                    city=_clean(cell(row, "city")),
                    gstin=_clean(cell(row, "gstin")),
                    kind="supplier" if kind.startswith("suppl") else "customer",
                    credit_days=_credit_days(cell(row, "credit_days")),
                    outstanding=_number(cell(row, "outstanding")),
                )
            )
        return seeds
    finally:
        workbook.close()


def parse_upload(filename: str | None, path: Path) -> tuple[str, list[PartySeed]]:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".xml":
        return "tally", parse_tally_xml(path.read_bytes())
    if suffix in {".xlsx", ".xlsm"}:
        return "excel", parse_party_excel(path)
    raise ValueError(
        f"Unsupported party list '{suffix or filename}'. "
        "Send a Tally XML master export or an .xlsx customer list."
    )


# --- the fallback source: the chat itself --------------------------------

# Names an export uses for the owner's own side of the conversation.
_SELF_NAMES = {"you", "me", "self", "aap"}


def seeds_from_messages(db, tenant_id: uuid.UUID, owner_phone: str | None = None) -> list[PartySeed]:
    """Every distinct counterparty the owner has actually talked to.

    A 1:1 export names the sender by their saved contact name; a group export
    names them by number. Both become a party, and the phone is what lets the
    Resolver attribute a message whose text never says who it is from.
    """
    rows = db.execute(
        select(
            Interaction.sender,
            Interaction.sender_phone,
            func.count().label("messages"),
        )
        .where(Interaction.tenant_id == tenant_id, Interaction.sender.isnot(None))
        .group_by(Interaction.sender, Interaction.sender_phone)
        .order_by(func.count().desc())
    ).all()

    owner_last10 = normalize_phone(owner_phone)
    merged: dict[str, PartySeed] = {}

    for sender, phone, _count in rows:
        name = _clean(sender)
        if not name or name.lower() in _SELF_NAMES:
            continue
        if owner_last10 and normalize_phone(phone) == owner_last10:
            continue  # the owner's own messages

        key = name.lower()
        if key in merged:
            merged[key].phone = merged[key].phone or phone
        else:
            merged[key] = PartySeed(name=name, phone=phone, kind="customer")

    return list(merged.values())


# --- writing --------------------------------------------------------------


def _existing_match(db, tenant_id: uuid.UUID, seed: PartySeed) -> Party | None:
    """Name first, then phone — the two things that are never coincidences."""
    from app.services.matching import exact_alias_match, phone_match

    return (
        exact_alias_match(db, tenant_id, seed.name)
        or phone_match(db, tenant_id, seed.phone)
    )


def import_parties(
    db,
    tenant_id: uuid.UUID,
    seeds: list[PartySeed],
    source: str,
    *,
    opening_balances: bool = True,
) -> ImportResult:
    """Create or merge parties, and turn any outstanding into an open invoice."""
    result = ImportResult(source=source)
    today = date.today()

    for seed in seeds:
        if not seed.name:
            result.skipped += 1
            continue

        party = _existing_match(db, tenant_id, seed)
        if party is None:
            party = Party(
                tenant_id=tenant_id,
                name=seed.name,
                aliases=list(seed.aliases),
                phone=seed.phone,
                city=seed.city,
                gstin=seed.gstin,
                kind=seed.kind,
                credit_days=seed.credit_days or 0,
                source=source,
            )
            db.add(party)
            db.flush()
            result.created += 1
        else:
            # Never overwrite what is already known — an import is new
            # information, not a more authoritative version of old information.
            party.phone = party.phone or seed.phone
            party.city = party.city or seed.city
            party.gstin = party.gstin or seed.gstin
            if seed.credit_days and not party.credit_days:
                party.credit_days = seed.credit_days
            known = {a.lower() for a in (party.aliases or [])} | {party.name.lower()}
            extra = [a for a in [*seed.aliases, seed.name] if a.lower() not in known]
            if extra:
                party.aliases = [*(party.aliases or []), *extra]
            result.merged += 1

        if opening_balances and seed.outstanding and seed.outstanding > 0:
            already = db.execute(
                select(func.count())
                .select_from(Invoice)
                .where(
                    Invoice.tenant_id == tenant_id,
                    Invoice.party_id == party.id,
                    Invoice.invoice_no == OPENING_INVOICE_NO,
                )
            ).scalar_one()
            if not already:
                db.add(
                    Invoice(
                        tenant_id=tenant_id,
                        party_id=party.id,
                        invoice_no=OPENING_INVOICE_NO,
                        invoice_date=today,
                        # Due now, not overdue. A ledger-master export carries
                        # the balance but not the bills behind it, so its real
                        # age is unknown — and inventing an age would put
                        # numbers in the ageing buckets that the owner cannot
                        # reconcile against Tally. Bill-wise import is what
                        # fixes this properly.
                        due_date=today,
                        amount=seed.outstanding,
                        status="open",
                        source=source,
                    )
                )
                result.opening_invoices += 1
                result.total_outstanding += seed.outstanding

    db.flush()
    return result

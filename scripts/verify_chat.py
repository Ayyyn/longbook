"""Verification for chat over a business's own records.

Three properties, in order of how much damage their absence would do:

1. Tenant A can never retrieve tenant B's data through chat. Enforced at the
   query layer, so it is tested at the query layer and again through the API.
2. Every factual claim carries a citation that resolves. An invented one is
   stripped rather than shown.
3. With no records, it says so instead of inventing an answer.

The model is stubbed. What is under test is retrieval and the citation
guarantee, neither of which should depend on what Gemini feels like saying.

    DATABASE_URL=... PYTHONPATH=. python scripts/verify_chat.py
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

from app.db import admin_session, tenant_session
from app.models import BusinessProfile, Interaction, Invoice, Party, Tenant
from app.services.auth import issue_token
from app.services.retrieval import as_prompt, citation_map, gather

ok = fail = 0


def check(label: str, got, want) -> None:
    global ok, fail
    if got == want:
        ok += 1
        print(f"  PASS  {label}")
    else:
        fail += 1
        print(f"  FAIL  {label}\n          got={got!r}\n         want={want!r}")


def make_tenant(name: str, party: str, amount: float, secret: str):
    tid = uuid.uuid4()
    with admin_session() as db:
        t = Tenant(id=tid, business_name=name,
                   owner_phone=f"98{uuid.uuid4().int % 10**8:08d}",
                   onboarded_at=datetime.utcnow())
        token = issue_token(t)
        db.add(t)
    with tenant_session(tid) as db:
        db.add(BusinessProfile(tenant_id=tid, segments=["wholesaler"], modules={},
                               vocabulary={}, rules={}, examples=[]))
        p = Party(tenant_id=tid, name=party, phone="9876500000")
        db.add(p)
        db.flush()
        db.add(Invoice(tenant_id=tid, party_id=p.id, invoice_no=f"INV-{secret}",
                       invoice_date=date.today() - timedelta(days=70),
                       amount=amount, status="open"))
        db.add(Interaction(tenant_id=tid, channel="whatsapp_export", sender=party,
                           occurred_at=datetime.utcnow(),
                           body=f"{secret} confidential rate 999 for {party}",
                           thread_key="t", dedupe_hash=uuid.uuid4().hex))
    return tid, token


A, TOKEN_A = make_tenant("Alpha Mills", "Ashok Textiles", 25000, "ALPHASECRET")

# A tenant with a party but nothing owed, for the "nothing outstanding" case.
EMPTY_FOR_MONEY = uuid.uuid4()
with admin_session() as db:
    db.add(Tenant(id=EMPTY_FOR_MONEY, business_name="Nil Mills",
                  owner_phone=f"96{uuid.uuid4().int % 10**8:08d}"))
with tenant_session(EMPTY_FOR_MONEY) as db:
    db.add(BusinessProfile(tenant_id=EMPTY_FOR_MONEY, segments=["wholesaler"],
                           modules={}, vocabulary={}, rules={}, examples=[]))
    db.add(Party(tenant_id=EMPTY_FOR_MONEY, name="Nobody Owes Us", phone="9000000000"))
B, TOKEN_B = make_tenant("Beta Mills", "Bharat Fabrics", 91000, "BETASECRET")

print("\n-- isolation at the query layer --")

ctx_a = gather(None, A, "who owes me the most") if False else None
with tenant_session(A) as db:
    ctx_a = gather(db, A, "who owes me the most money")
rendered_a = as_prompt(ctx_a)
check("A sees its own party", "Ashok Textiles" in rendered_a, True)
check("A DOES NOT SEE B's PARTY", "Bharat Fabrics" in rendered_a, False)
check("  nor B's amount", "91,000" in rendered_a, False)
check("  nor B's invoice number", "BETASECRET" in rendered_a, False)

with tenant_session(A) as db:
    leak = gather(db, A, "BETASECRET Bharat Fabrics confidential")
check("searching for B's own words from A finds nothing of B's",
      "BETASECRET" in as_prompt(leak), False)
check("  and no party of B's", "Bharat Fabrics" in as_prompt(leak), False)

with tenant_session(B) as db:
    ctx_b = gather(db, B, "who owes me the most money")
check("B sees its own", "Bharat Fabrics" in as_prompt(ctx_b), True)
check("  and none of A's", "Ashok Textiles" in as_prompt(ctx_b), False)

print("\n-- undispatched orders, and the NOT IN trap --")

from app.models import Dispatch, Order, OrderLine  # noqa: E402

with tenant_session(A) as db:
    party = db.query(Party).first()
    db.add(Order(tenant_id=A, party_id=party.id, order_no="ORD-1",
                 order_date=date.today(), status="draft"))
    db.add(Order(tenant_id=A, party_id=party.id, order_no="ORD-2",
                 order_date=date.today(), status=None))
    db.flush()
    # A dispatch row with a NULL order_id is what poisons `NOT IN`: one NULL in
    # the subquery makes the predicate NULL for every row, so the query returns
    # nothing instead of everything undispatched.
    db.add(Dispatch(tenant_id=A, order_id=None, dispatched_on=date.today()))

with tenant_session(A) as db:
    ctx_orders = gather(db, A, "which orders have not been dispatched")
check("undispatched orders survive a NULL order_id in dispatch",
      len(ctx_orders.orders) >= 2, True)
check("  including one whose status is NULL",
      any("ORD-2" in e.label for e in ctx_orders.orders), True)

with tenant_session(A) as db:
    target = db.query(Order).filter(Order.order_no == "ORD-1").first()
    db.add(OrderLine(tenant_id=A, order_id=target.id,
                     raw_description="Spindle bolster", quantity=None, rate=None))

with tenant_session(A) as db:
    ctx_nullqty = gather(db, A, "which orders have not been dispatched")
check("a line with no quantity does not crash the answer",
      any("quantity not stated" in e.detail for e in ctx_nullqty.orders), True)

print("\n-- nothing owed is a fact, not a gap --")

with tenant_session(EMPTY_FOR_MONEY) as db:
    ctx_nil = gather(db, EMPTY_FOR_MONEY, "who owes me the most")
check("it states that nobody owes anything",
      "Nobody owes this business" in as_prompt(ctx_nil), True)

print("\n-- citations resolve --")

with tenant_session(A) as db:
    ctx = gather(db, A, "who owes me the most money")
refs = citation_map(ctx)
check("references were produced", len(refs) > 0, True)
check("  every one resolves to a record",
      all(r.kind and r.label for r in refs.values()), True)
check("  and each carries an id to trace",
      all(r.party_id or r.order_id or r.interaction_id or r.record_id
          for r in refs.values()), True)

print("\n-- the answer is checked, not trusted --")

import app.agents.analyst as analyst_module  # noqa: E402

# Claims a fact citing a reference that does not exist. The analyst now drives
# tools rather than a single JSON call, so the stub stands in for the tool loop
# and returns (answer, trace, usage).
def lying(*, model, system, user, tools=None, history=None, max_steps=6):
    return (
        "Bharat Fabrics owes Rs 91,000 [P9].",
        [],
        {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0001},
    )


analyst_module.generate_with_tools = lying
from app.agents.analyst import Analyst  # noqa: E402

with tenant_session(A) as db:
    decision = Analyst(db, A).run({"question": "who owes me the most"})
check("an invented citation is not shown", "[P9]" in decision.output["answer"], False)
check("  and the claim is withdrawn rather than shown uncited",
      decision.output["answered"], False)
check("  the invention is recorded", decision.output["invented_citations"], ["P9"])


# Actually calls a lookup, so the reference it cites is one the wrapper really
# issued. That exercises the whole path: tool -> row -> short token -> citation
# -> source with a record id the UI can link to.
def honest(*, model, system, user, tools=None, history=None, max_steps=6):
    rows = tools["outstanding"]["run"]()["rows"]
    trace = [{"tool": "outstanding", "args": {}, "rows": len(rows)}]
    if not rows:
        # A tenant with nothing in it: the lookup ran and came back empty, so
        # the honest answer names no figure and cites nothing.
        return ("There is nothing on record for this business yet.", trace,
                {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0001})
    return (
        f"Ashok Textiles owes Rs 25,000 [{rows[0]['ref']}].",
        trace,
        {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0001},
    )


analyst_module.generate_with_tools = honest
with tenant_session(A) as db:
    good = Analyst(db, A).run({"question": "who owes me the most"})
check("a real citation is kept", good.output["answered"], True)
check("  and resolves to a source", len(good.output["sources"]), 1)
check("  naming the record", good.output["sources"][0]["label"], "Ashok Textiles")
check("  with an id the UI can link to", bool(good.output["sources"][0]["party_id"]), True)

print("\n-- nothing to answer from --")

EMPTY = uuid.uuid4()
with admin_session() as db:
    t = Tenant(id=EMPTY, business_name="Empty Mills",
               owner_phone=f"97{uuid.uuid4().int % 10**8:08d}")
    EMPTY_TOKEN = issue_token(t)
    db.add(t)
with tenant_session(EMPTY) as db:
    db.add(BusinessProfile(tenant_id=EMPTY, segments=["wholesaler"], modules={},
                           vocabulary={}, rules={}, examples=[]))

with tenant_session(EMPTY) as db:
    nothing = Analyst(db, EMPTY).run({"question": "who owes me the most"})
check("it says it has nothing", nothing.output["answered"], False)
check("  without inventing a figure", "25,000" in nothing.output["answer"], False)
check("  and cites nothing", nothing.output["sources"], [])

print("\n-- through the API --")

import app.api.chat as chat_module  # noqa: E402

chat_module.Analyst = Analyst
from app.main import app  # noqa: E402

client = TestClient(app)

resp = client.post("/api/chat", headers={"Authorization": f"Bearer {TOKEN_A}"},
                   json={"question": "who owes me the most"})
check("the endpoint answers", resp.status_code, 200)
body = resp.json()
check("  with sources", len(body["sources"]) >= 1, True)
check("  AND NOTHING OF B'S", "Bharat" in resp.text, False)
check("  reporting latency", body["latency_ms"] >= 0, True)
check("  and cost", body["cost_usd"] is not None, True)

check("chat needs a token", client.post("/api/chat",
                                        json={"question": "hi"}).status_code, 401)
check("suggestions are offered",
      len(client.get("/api/chat/suggestions",
                     headers={"Authorization": f"Bearer {TOKEN_A}"}).json()["questions"]) >= 3,
      True)

print("\n-- every turn is logged --")

from app.models import AgentRun  # noqa: E402

with tenant_session(A) as db:
    runs = db.query(AgentRun).filter(AgentRun.agent == "analyst").count()
check("the question reached agent_run", runs >= 1, True)

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)

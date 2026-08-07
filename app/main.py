"""FastAPI entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    agents,
    ingest,
    jobs,
    ledger,
    orders,
    parties,
    review,
    tenants,
    today,
)

app = FastAPI(title="Textile Ops", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten before any real customer data lands
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tenants.router, prefix="/api/tenants", tags=["tenants"])
app.include_router(ingest.router, prefix="/api/ingest", tags=["ingest"])
app.include_router(review.router, prefix="/api/review", tags=["review"])
app.include_router(ledger.router, prefix="/api/ledger", tags=["ledger"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(today.router, prefix="/api/today", tags=["today"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(parties.router, prefix="/api/parties", tags=["parties"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])


@app.get("/health")
def health():
    return {"ok": True}

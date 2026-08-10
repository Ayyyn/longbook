"""FastAPI entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fastapi import Depends

from app.config import settings
from app.api.deps import require_access
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

def _allowed_origins() -> list[str]:
    """Who may call this from a browser.

    The tenant token lives in the dashboard's local storage, so a permissive
    origin list is how it would leak. One deployment serves one frontend;
    anything else has to be named explicitly.
    """
    configured = settings().cors_origins
    origins = (
        [o.strip() for o in configured.split(",") if o.strip()]
        if configured
        else [settings().dashboard_url, "http://localhost:3000"]
    )
    return list(dict.fromkeys(origins))


app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tenants.router, prefix="/api/tenants", tags=["tenants"])
app.include_router(ingest.router, prefix="/api/ingest", tags=["ingest"],
                   dependencies=[Depends(require_access)])
app.include_router(review.router, prefix="/api/review", tags=["review"],
                   dependencies=[Depends(require_access)])
app.include_router(ledger.router, prefix="/api/ledger", tags=["ledger"],
                   dependencies=[Depends(require_access)])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"],
                   dependencies=[Depends(require_access)])
app.include_router(today.router, prefix="/api/today", tags=["today"],
                   dependencies=[Depends(require_access)])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(parties.router, prefix="/api/parties", tags=["parties"],
                   dependencies=[Depends(require_access)])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"],
                   dependencies=[Depends(require_access)])


@app.get("/health")
def health():
    return {"ok": True}

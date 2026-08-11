from app.agents.analyst import Analyst
from app.agents.base import Agent, Decision
from app.agents.configurator import Configurator
from app.agents.extractor import Extractor
from app.agents.interviewer import Interviewer
from app.agents.resolver import Resolver
from app.agents.triage import Triage
from app.agents.ledger_analyst import LedgerAnalyst
from app.agents.digest import DigestComposer
from app.agents.draft_composer import DraftComposer

__all__ = [
    "Agent",
    "Decision",
    "Configurator",
    "Extractor",
    "Resolver",
    "Triage",
    "LedgerAnalyst",
    "DigestComposer",
    "DraftComposer",
    "Analyst",
    "Interviewer",
    "REGISTRY",
]

REGISTRY = {
    "configurator": Configurator,
    "extractor": Extractor,
    "resolver": Resolver,
    "triage": Triage,
    "ledger_analyst": LedgerAnalyst,
    "digest_composer": DigestComposer,
    "draft_composer": DraftComposer,
    "analyst": Analyst,
    "interviewer": Interviewer,
}

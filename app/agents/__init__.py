from app.agents.base import Agent, Decision
from app.agents.configurator import Configurator
from app.agents.extractor import Extractor
from app.agents.resolver import Resolver
from app.agents.triage import Triage
from app.agents.ledger_analyst import LedgerAnalyst
from app.agents.digest import DigestComposer
from app.agents.draft_composer import DraftComposer

REGISTRY = {
    "configurator": Configurator,
    "extractor": Extractor,
    "resolver": Resolver,
    "triage": Triage,
    "ledger_analyst": LedgerAnalyst,
    "digest_composer": DigestComposer,
    "draft_composer": DraftComposer,
}

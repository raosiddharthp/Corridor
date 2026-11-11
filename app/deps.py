"""Builds the services the run API needs from the environment."""
import functools
import logging
import os
from dataclasses import dataclass

import httpx

from pipeline import keys as pkeys
from pipeline import negotiation
from pipeline.approvals import MemoryApprovalStore
from pipeline.challenge import MemoryChallengeStore
from pipeline.events import MemoryEventLog
from pipeline.gemini import build_interpreter
from pipeline.ledger import MemorySpendLedger
from pipeline.orchestrator import Orchestrator
from pipeline.payments import PaymentExecutor

log = logging.getLogger(__name__)


class NotConfigured(RuntimeError):
    pass


@dataclass
class Services:
    keys: object
    supplier_url: str
    http: httpx.AsyncClient
    events: MemoryEventLog
    challenges: MemoryChallengeStore
    ledger: MemorySpendLedger
    interpreter: object
    executor: PaymentExecutor
    approvals: MemoryApprovalStore


def build_services(env=None) -> Services:
    env = os.environ if env is None else env
    url = env.get("SUPPLIER_URL", "")
    if not url:
        raise NotConfigured("SUPPLIER_URL is not set")
    try:
        key_set = pkeys.load_keys(env)
    except pkeys.KeyConfigError:
        log.error("signing keys are missing or invalid", exc_info=True)
        raise NotConfigured("signing keys are not configured") from None
    ledger = MemorySpendLedger()
    return Services(
        keys=key_set,
        supplier_url=url,
        http=httpx.AsyncClient(timeout=10),
        events=MemoryEventLog(),
        challenges=MemoryChallengeStore(),
        ledger=ledger,
        interpreter=build_interpreter(env),
        executor=PaymentExecutor(ledger),
        approvals=MemoryApprovalStore(),
    )


def orchestrator_factory(services: Services):
    def make(demo_hostile: bool) -> Orchestrator:
        quote = (
            functools.partial(negotiation.request_quote, demo_hostile=True)
            if demo_hostile
            else negotiation.request_quote
        )
        return Orchestrator(
            keys=services.keys,
            supplier_url=services.supplier_url,
            http=services.http,
            events=services.events,
            challenges=services.challenges,
            ledger=services.ledger,
            interpreter=services.interpreter,
            quote=quote,
            executor=services.executor,
            approvals=services.approvals,
        )

    return make

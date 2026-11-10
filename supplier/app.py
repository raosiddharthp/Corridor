"""Supplier agent: an A2A server for BrunnerTeknik (a scripted counterparty)."""
import inspect

from a2a.helpers.proto_helpers import new_data_part, new_task, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, TaskState
from fastapi import FastAPI
from jwcrypto.jwk import JWK

from supplier.quotes import UnknownOrder, make_quote

RPC_PATH = "/a2a"
HOSTILE_MARKER = "[demo:hostile]"


async def _maybe(result):
    """Await the result if it is awaitable; the SDK mixes sync and async helpers."""
    if inspect.isawaitable(result):
        return await result
    return result


def parse_request(text: str) -> tuple[str, bool]:
    tokens = text.split()
    if len(tokens) < 2 or tokens[0] != "quote":
        raise UnknownOrder("expected: quote <order ref>")
    return tokens[1], HOSTILE_MARKER in tokens[2:]


class SupplierExecutor(AgentExecutor):
    def __init__(self, supplier_key: JWK):
        self._key = supplier_key

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        has_task = getattr(context, "current_task", None) or getattr(context, "task", None)
        if not has_task:
            task = new_task(context.task_id, context.context_id, TaskState.TASK_STATE_SUBMITTED)
            await _maybe(event_queue.enqueue_event(task))
        await _maybe(updater.start_work())
        try:
            ref, hostile = parse_request(context.get_user_input())
            quote = make_quote(ref, self._key, hostile=hostile)
        except UnknownOrder as exc:
            message = updater.new_agent_message([new_text_part(str(exc))])
            await _maybe(updater.failed(message))
            return
        except Exception:
            message = updater.new_agent_message([new_text_part("the supplier could not produce a quote")])
            await _maybe(updater.failed(message))
            return
        await _maybe(updater.add_artifact([new_data_part(quote.to_dict())], name="quote"))
        await _maybe(updater.complete(updater.new_agent_message([new_text_part(quote.note)])))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await _maybe(updater.cancel())


def build_card(base_url: str) -> AgentCard:
    return AgentCard(
        name="BrunnerTeknik sales agent",
        description="Quotes trade orders for BrunnerTeknik GmbH. A scripted counterparty for the Corridor demo.",
        version="0.1.0",
        supported_interfaces=[
            AgentInterface(url=base_url + RPC_PATH, protocol_binding="JSONRPC", protocol_version="1.0")
        ],
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text/plain"],
        default_output_modes=["application/json"],
        skills=[
            AgentSkill(
                id="quote",
                name="Quote an order",
                description="Returns a price and a supplier-signed checkout for an order reference.",
                tags=["quote", "trade"],
                examples=["quote FP-88213"],
            )
        ],
    )


def create_app(supplier_key: JWK, base_url: str) -> FastAPI:
    card = build_card(base_url)
    handler = DefaultRequestHandler(
        agent_executor=SupplierExecutor(supplier_key),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    app = FastAPI(title="Corridor supplier agent")
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url=RPC_PATH),
    )

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "supplier"}

    return app

"""Chat endpoints: conversation threads, paginated history, and SSE streaming.

The stream endpoint saves the user's message, builds the digital twin context
server-side, forwards the assistant bot's SSE events to the client, and only
persists the assistant response (plus citations and guardrail events) once
the stream has finished.
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_patient
from app.api.schemas.chat import (
    ChatHistoryItem,
    ChatMessageCreate,
    ChatRequest,
    ConversationCreate,
    ConversationResponse,
    MessagePage,
    MessageResponse,
)
from app.core.db import SessionLocal, get_db
from app.core.rate_limit import limiter
from app.models.chat import Citation, Conversation, GuardrailEvent, Message, SenderEnum
from app.models.users import Patient
from app.services.assistant_bot import stream_assistant_bot
from app.services.twin_context import build_digital_twin_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/conversations", tags=["Chat"])

# Prior messages sent to the assistant bot for conversational memory.
HISTORY_LIMIT = 20
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
# Bot status values that must be recorded in guardrail_events. MeSquareAssistantBot
# emits these from its topic detector (emergency/off_topic), medication gate, and
# verifier nodes.
GUARDRAIL_EVENT_TYPES = {"medication_prohibited", "off_topic", "emergency"}


async def _get_owned_conversation(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Conversation:
    """Fetch a conversation owned by the user; 404 hides other users' threads."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationResponse]:
    """Return all conversation threads for the authenticated user."""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == patient.user_id)
        .order_by(Conversation.updated_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    payload: ConversationCreate | None = None,
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
) -> Conversation:
    """Create a new conversation thread for the authenticated user."""
    payload = payload or ConversationCreate()
    conversation = Conversation(
        user_id=patient.user_id,
        title=payload.title or "New conversation",
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.get("/{conversation_id}/messages", response_model=MessagePage)
async def list_messages(
    conversation_id: uuid.UUID,
    before_id: uuid.UUID | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
) -> MessagePage:
    """Return one page of message history (chronological order) with citations.

    Keyset pagination: pass the returned next_before_id to fetch the next
    older page. This avoids the drift and scan cost of OFFSET pagination on
    an append-heavy table.
    """
    conversation = await _get_owned_conversation(db, conversation_id, patient.user_id)

    statement = (
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .options(selectinload(Message.citations))
    )
    if before_id is not None:
        anchor_result = await db.execute(
            select(Message).where(
                Message.id == before_id,
                Message.conversation_id == conversation.id,
            )
        )
        anchor = anchor_result.scalar_one_or_none()
        if anchor is None:
            raise HTTPException(
                status_code=404,
                detail="before_id does not reference a message in this conversation.",
            )
        # Strictly older than the anchor (created_at with an id tiebreaker).
        statement = statement.where(
            (Message.created_at < anchor.created_at)
            | ((Message.created_at == anchor.created_at) & (Message.id < anchor.id))
        )

    statement = statement.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1)
    rows = (await db.execute(statement)).scalars().all()

    has_more = len(rows) > limit
    page = list(reversed(rows[:limit]))  # chronological order for display
    return MessagePage(
        messages=page,
        next_before_id=page[0].id if has_more and page else None,
    )

@router.post("/{conversation_id}/messages/stream")
@limiter.limit("10/minute")
async def stream_message(
    request: Request,
    conversation_id: uuid.UUID,
    payload: ChatMessageCreate,
    patient: Patient = Depends(get_current_patient),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream an assistant reply to the user's message as SSE events."""
    conversation = await _get_owned_conversation(db, conversation_id, patient.user_id)

    # Build the twin context and load history server-side: clients must never
    # be able to feed fabricated health data or fake history to the bot.
    twin_context = await build_digital_twin_context(db, patient)
    history = await _load_history(db, conversation.id)

    user_message = Message(
        id=payload.client_message_id or uuid.uuid4(),
        conversation_id=conversation.id,
        sender_type=SenderEnum.user,
        content=payload.query,
        twin_snapshot=twin_context.model_dump(mode="json"),
    )
    db.add(user_message)
    try:
        # This UPDATE triggers an autoflush of user_message, so a duplicate
        # client_message_id surfaces here, not only at commit time.
        await db.execute(
            update(Conversation)
            .where(Conversation.id == conversation.id)
            .values(updated_at=func.now())
        )
        await db.commit()
    except IntegrityError:
        # client_message_id was already saved: treat the retry as a duplicate.
        await db.rollback()
        raise HTTPException(status_code=409, detail="This message has already been processed.")
    await db.refresh(user_message)

    bot_request = ChatRequest(
        conversation_id=conversation.id,
        message_id=user_message.id,
        query=payload.query,
        twin_context=twin_context,
        history=history,
    )

    return StreamingResponse(
        _forward_bot_stream(
            bot_request.model_dump(mode="json"),
            conversation_id=conversation.id,
            user_id=patient.user_id,
            user_query=payload.query,
            twin_snapshot=user_message.twin_snapshot,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Disable reverse-proxy buffering (e.g. nginx) so tokens arrive
            # as they are generated.
            "X-Accel-Buffering": "no",
        },
    )


async def _load_history(
    db: AsyncSession, conversation_id: uuid.UUID
) -> list[ChatHistoryItem]:
    """The most recent messages of the conversation, oldest first."""
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(HISTORY_LIMIT)
    )
    return [
        ChatHistoryItem(role=message.sender_type.value, content=message.content)
        for message in reversed(result.scalars().all())
    ]


def _format_sse(event: str, data: object) -> str:
    """Serialize one SSE frame: an event name plus a JSON data payload."""
    try:
        serialized = json.dumps(data)
    except (TypeError, ValueError):
        serialized = json.dumps(str(data))
    return f"event: {event}\ndata: {serialized}\n\n"


def _extract_token_text(data: object) -> str:
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for key in ("token", "text", "content", "delta"):
            value = data.get(key)
            if isinstance(value, str):
                return value
    return ""


def _extract_status(data: object) -> str | None:
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        value = data.get("status")
        if isinstance(value, str):
            return value
    return None


def _extract_output_text(data: object) -> str | None:
    if isinstance(data, dict):
        value = data.get("output_text")
        if isinstance(value, str) and value:
            return value
    return None


def _extract_citations(data: object) -> list[dict[str, str | None]]:
    """Normalize the bot's citation payloads into chat.citations rows.

    MeSquareAssistantBot emits `event: citations` with data shaped as
    {"citations": [{"chunk_id", "guideline_title", "section_title", "excerpt"}]}
    (built by its verifier node). A bare list or single-item payload is also
    accepted defensively in case the bot's format evolves.
    """
    if isinstance(data, dict) and isinstance(data.get("citations"), list):
        items: list[object] = data["citations"]
    elif isinstance(data, list):
        items = data
    else:
        items = [data]

    result: list[dict[str, str | None]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source = (
            item.get("guideline_title")
            or item.get("guideline_source")
            or item.get("source")
        )
        if not isinstance(source, str) or not source:
            continue
        section = (
            item.get("section_title")
            or item.get("section_reference")
            or item.get("section")
        )
        excerpt = item.get("excerpt")
        result.append(
            {
                "guideline_source": source,
                "section_reference": section if isinstance(section, str) and section else None,
                "excerpt": excerpt if isinstance(excerpt, str) and excerpt else None,
            }
        )
    return result

async def _forward_bot_stream(
    bot_payload: dict[str, Any],
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    user_query: str,
    twin_snapshot: dict[str, Any] | None,
) -> AsyncIterator[str]:
    """Forward the bot's SSE events, then persist the assistant's response.

    Runs inside the StreamingResponse lifecycle, so it must not use the
    request-scoped database session: a fresh SessionLocal is opened in the
    finally block, which also runs when the client disconnects mid-stream, so
    partial responses are still saved.
    """
    token_parts: list[str] = []
    citations: list[dict[str, str | None]] = []
    guardrail_types: set[str] = set()

    try:
        async for event, data in stream_assistant_bot(bot_payload):
            if event == "token":
                text = _extract_token_text(data)
                if text:
                    token_parts.append(text)
            elif event in ("citations", "citation"):
                citations.extend(_extract_citations(data))
            elif event == "status":
                status_value = _extract_status(data)
                # Early exits (emergency/off_topic/medication_prohibited)
                # carry the bot's reply in output_text instead of token events.
                output_text = _extract_output_text(data)
                if output_text:
                    token_parts.append(output_text)
                if status_value in GUARDRAIL_EVENT_TYPES:
                    guardrail_types.add(status_value)
            yield _format_sse(event, data)
            if event == "done":
                break
    except httpx.HTTPError:
        logger.exception("Assistant bot stream failed for conversation %s", conversation_id)
        yield _format_sse(
            "error", {"detail": "The assistant is unavailable. Please try again later."}
        )
    except Exception:
        logger.exception(
            "Unexpected error forwarding assistant stream for conversation %s", conversation_id
        )
        yield _format_sse(
            "error", {"detail": "An unexpected error occurred while streaming the response."}
        )
    finally:
        if token_parts or citations or guardrail_types:
            try:
                await _persist_assistant_response(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    user_query=user_query,
                    assistant_text="".join(token_parts),
                    citations=citations,
                    guardrail_types=sorted(guardrail_types),
                    twin_snapshot=twin_snapshot,
                )
            except Exception:
                logger.exception(
                    "Failed to persist assistant response for conversation %s", conversation_id
                )


async def _persist_assistant_response(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    user_query: str,
    assistant_text: str,
    citations: list[dict[str, str | None]],
    guardrail_types: list[str],
    twin_snapshot: dict[str, Any] | None,
) -> None:
    """Insert the assistant message, its citations, and any guardrail events.

    Opens a fresh session because the Depends(get_db) session may already be
    closed by the time the streamed response finishes.
    """
    async with SessionLocal() as session:
        if assistant_text or citations:
            assistant_message = Message(
                conversation_id=conversation_id,
                sender_type=SenderEnum.assistant,
                content=assistant_text,
                twin_snapshot=twin_snapshot,
            )
            session.add(assistant_message)
            await session.flush()
            for citation in citations:
                session.add(Citation(message_id=assistant_message.id, **citation))
            await session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(updated_at=func.now())
            )
        for event_type in guardrail_types:
            session.add(
                GuardrailEvent(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    event_type=event_type,
                    user_query=user_query,
                )
            )
        await session.commit()
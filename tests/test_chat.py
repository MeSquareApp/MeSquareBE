"""Tests for the chat endpoints: threads, history pagination, and SSE streaming.

The assistant bot HTTP call is replaced with canned (event, data) pairs, so
these tests exercise the backend contract end to end without a live bot.
"""

import asyncio
import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.rate_limit import limiter
from app.models.chat import GuardrailEvent

CHAT_PREFIX = "/api/v1/conversations"


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """In-memory rate limit counters must not leak between tests."""
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def patient_client(auth):
    """A client authenticated as a user with a patient account."""
    resp = auth().post(
        "/users/me/create-m2-account",
        json={
            "first_name": "Jane",
            "last_name": "Doe",
            "role": "patient",
            "sex": "Female",
            "dob": "1990-05-01",
        },
    )
    assert resp.status_code == 201, resp.text
    return auth()


@pytest.fixture
def fake_bot(monkeypatch):
    """Replace the assistant-bot HTTP call with canned (event, data) pairs."""
    holder = {
        # Mirrors the real MeSquareAssistantBot SSE contract
        # (POST /internal/v1/chat/stream): token events, a single citations
        # event with a {"citations": [...]} wrapper, then done.
        "events": [
            ("token", {"token": "Based on your labs, "}),
            ("token", {"token": "everything looks stable."}),
            (
                "citations",
                {
                    "citations": [
                        {
                            "chunk_id": "chunk-1",
                            "guideline_title": "2023 ACC/AHA Multisociety Guideline",
                            "section_title": "Section 4.2",
                            "excerpt": "Lifestyle changes are recommended first-line.",
                        }
                    ]
                },
            ),
            ("done", {"status": "success"}),
        ],
        "payloads": [],
    }

    async def fake_stream(payload):
        holder["payloads"].append(payload)
        for event, data in holder["events"]:
            yield event, data

    monkeypatch.setattr("app.api.routes.chat.stream_assistant_bot", fake_stream)
    return holder


def _create_conversation(client, **body):
    resp = client.post(CHAT_PREFIX, json=body or {})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _stream_message(client, conversation_id, query="How are my labs?", **extra):
    return client.post(
        f"{CHAT_PREFIX}/{conversation_id}/messages/stream",
        json={"query": query, **extra},
    )


def _parse_sse(text):
    """Parse the raw SSE body into (event, data) pairs."""
    events = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        event, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        events.append((event, data))
    return events


def _fetch_guardrail_events():
    """Read guardrail_events directly from the test database."""

    async def run():
        # Throwaway engine: created and disposed on this test's event loop so
        # the application's pooled connections are never reused across loops.
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    select(GuardrailEvent.event_type, GuardrailEvent.user_query)
                )
                return sorted(rows.all())
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_chat_requires_authentication(client):
    assert client.get(CHAT_PREFIX).status_code == 401


def test_create_and_list_conversations(patient_client):
    first = _create_conversation(patient_client)
    second = _create_conversation(patient_client, title="Heart health")

    assert first["title"] == "New conversation"
    assert second["title"] == "Heart health"

    resp = patient_client.get(CHAT_PREFIX)
    assert resp.status_code == 200
    assert {c["id"] for c in resp.json()} == {first["id"], second["id"]}


def test_conversations_are_scoped_to_their_owner(patient_client, auth):
    _create_conversation(patient_client)

    other = auth(sub="auth0|chat-other", email="other@test.com")
    resp = other.post(
        "/users/me/create-m2-account",
        json={
            "first_name": "John",
            "last_name": "Roe",
            "role": "patient",
            "sex": "Male",
            "dob": "1985-01-01",
        },
    )
    assert resp.status_code == 201, resp.text
    assert other.get(CHAT_PREFIX).json() == []


def test_messages_reject_other_users_conversation(patient_client, auth):
    conversation = _create_conversation(patient_client)

    other = auth(sub="auth0|chat-other-2", email="other2@test.com")
    assert (
        other.post(
            "/users/me/create-m2-account",
            json={
                "first_name": "John",
                "last_name": "Roe",
                "role": "patient",
                "sex": "Male",
                "dob": "1985-01-01",
            },
        ).status_code
        == 201
    )
    # 404 (not 403) so one user cannot probe for another user's conversation ids.
    resp = other.get(f"{CHAT_PREFIX}/{conversation['id']}/messages")
    assert resp.status_code == 404

    resp = other.post(f"{CHAT_PREFIX}/{conversation['id']}/messages/stream", json={"query": "hi"})
    assert resp.status_code == 404

def test_stream_persists_messages_and_citations(patient_client, fake_bot):
    conversation = _create_conversation(patient_client)
    resp = _stream_message(patient_client, conversation["id"], query="How are my labs?")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    assert [event for event, _ in events] == ["token", "token", "citations", "done"]
    assert events[0][1] == {"token": "Based on your labs, "}

    # The payload sent to the bot is built server-side.
    payload = fake_bot["payloads"][0]
    assert payload["query"] == "How are my labs?"
    assert payload["conversation_id"] == conversation["id"]
    assert payload["history"] == []
    twin = payload["twin_context"]
    # sex is normalized to the bot's Literal["male", "female"] contract.
    assert twin["sex"] == "female"
    assert twin["age"] is not None

    page = patient_client.get(f"{CHAT_PREFIX}/{conversation['id']}/messages").json()
    assert [m["sender_type"] for m in page["messages"]] == ["user", "assistant"]
    assert page["next_before_id"] is None

    user_msg, assistant_msg = page["messages"]
    assert user_msg["content"] == "How are my labs?"
    # The twin snapshot on the user message is an audit trail of what the bot saw.
    assert user_msg["twin_snapshot"]["user_id"] == twin["user_id"]
    assert assistant_msg["content"] == "Based on your labs, everything looks stable."
    assert len(assistant_msg["citations"]) == 1
    assert (
        assistant_msg["citations"][0]["guideline_source"]
        == "2023 ACC/AHA Multisociety Guideline"
    )
    assert assistant_msg["citations"][0]["section_reference"] == "Section 4.2"


def test_history_is_loaded_server_side(patient_client, fake_bot):
    conversation = _create_conversation(patient_client)
    _stream_message(patient_client, conversation["id"], query="First question")
    _stream_message(patient_client, conversation["id"], query="Second question")

    history = fake_bot["payloads"][1]["history"]
    assert [(m["role"], m["content"]) for m in history] == [
        ("user", "First question"),
        ("assistant", "Based on your labs, everything looks stable."),
    ]


def test_guardrail_events_are_recorded(patient_client, fake_bot):
    conversation = _create_conversation(patient_client)
    fake_bot["events"] = [
        (
            "status",
            {
                "status": "medication_prohibited",
                "output_text": "I cannot provide medication advice. Please consult your physician.",
            },
        ),
        ("done", {"status": "medication_prohibited", "total_citations": 0}),
    ]
    resp = _stream_message(patient_client, conversation["id"], query="Can I take aspirin daily?")
    assert resp.status_code == 200

    assert [event for event, _ in _parse_sse(resp.text)] == ["status", "done"]
    assert _fetch_guardrail_events() == [
        ("medication_prohibited", "Can I take aspirin daily?")
    ]

    # The early-exit reply (delivered in the status event's output_text, not
    # as token events) is still persisted as the assistant message.
    page = patient_client.get(f"{CHAT_PREFIX}/{conversation['id']}/messages").json()
    assert [m["sender_type"] for m in page["messages"]] == ["user", "assistant"]
    assert page["messages"][1]["content"] == (
        "I cannot provide medication advice. Please consult your physician."
    )


def test_emergency_status_records_guardrail_event(patient_client, fake_bot):
    conversation = _create_conversation(patient_client)
    fake_bot["events"] = [
        (
            "status",
            {
                "status": "emergency",
                "output_text": "EMERGENCY NOTICE: Please call 911 immediately.",
            },
        ),
        ("done", {"status": "emergency", "total_citations": 0}),
    ]
    resp = _stream_message(patient_client, conversation["id"], query="I have chest pain")
    assert resp.status_code == 200

    assert _fetch_guardrail_events() == [("emergency", "I have chest pain")]
    page = patient_client.get(f"{CHAT_PREFIX}/{conversation['id']}/messages").json()
    assert page["messages"][1]["content"] == (
        "EMERGENCY NOTICE: Please call 911 immediately."
    )


def test_bot_failure_emits_error_event(patient_client, fake_bot, monkeypatch):
    conversation = _create_conversation(patient_client)

    async def broken_stream(payload):
        raise httpx.ConnectError("bot is down")
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr("app.api.routes.chat.stream_assistant_bot", broken_stream)
    resp = _stream_message(patient_client, conversation["id"])
    assert resp.status_code == 200

    events = _parse_sse(resp.text)
    assert events == [("error", {"detail": "The assistant is unavailable. Please try again later."})]

    # No assistant message is persisted when nothing was streamed.
    page = patient_client.get(f"{CHAT_PREFIX}/{conversation['id']}/messages").json()
    assert [m["sender_type"] for m in page["messages"]] == ["user"]


def test_message_history_pagination(patient_client, fake_bot):
    conversation = _create_conversation(patient_client)
    for i in range(3):
        resp = _stream_message(patient_client, conversation["id"], query=f"Question {i}")
        assert resp.status_code == 200, resp.text

    # 6 messages total (3 user + 3 assistant).
    first_page = patient_client.get(
        f"{CHAT_PREFIX}/{conversation['id']}/messages", params={"limit": 4}
    ).json()
    assert len(first_page["messages"]) == 4
    assert first_page["next_before_id"] == first_page["messages"][0]["id"]

    second_page = patient_client.get(
        f"{CHAT_PREFIX}/{conversation['id']}/messages",
        params={"limit": 4, "before_id": first_page["next_before_id"]},
    ).json()
    assert len(second_page["messages"]) == 2
    assert second_page["next_before_id"] is None

    # Pages do not overlap and are in chronological order within each page.
    ids = [m["id"] for m in first_page["messages"]] + [m["id"] for m in second_page["messages"]]
    assert len(set(ids)) == 6


def test_client_message_id_is_idempotent(patient_client, fake_bot):
    conversation = _create_conversation(patient_client)
    message_id = "11111111-1111-1111-1111-111111111111"

    first = _stream_message(patient_client, conversation["id"], client_message_id=message_id)
    assert first.status_code == 200

    second = _stream_message(patient_client, conversation["id"], client_message_id=message_id)
    assert second.status_code == 409


def test_stream_is_rate_limited(patient_client, fake_bot):
    conversation = _create_conversation(patient_client)
    statuses = [
        _stream_message(patient_client, conversation["id"], query=f"q{i}").status_code
        for i in range(11)
    ]
    assert statuses[:10] == [200] * 10
    assert statuses[10] == 429

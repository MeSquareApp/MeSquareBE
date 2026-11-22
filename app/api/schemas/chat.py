"""Pydantic schemas for the chat (conversation service) endpoints."""

import uuid
from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class LabAnchors(BaseModel):
    """Most recent lab values; every field stays null until the patient has
    that measurement."""
    total_cholesterol: Optional[float] = None
    hdl: Optional[float] = None
    ldl: Optional[float] = None
    systolic_bp: Optional[float] = None
    diastolic_bp: Optional[float] = None
    fasting_glucose: Optional[float] = None
    hba1c: Optional[float] = None
    anchor_date: Optional[date] = None


class WearablesSummary(BaseModel):
    """14-day rolling averages computed from wearable time series."""
    resting_heart_rate_avg_14d: Optional[float] = None
    step_count_avg_14d: Optional[float] = None
    sleep_hours_avg_14d: Optional[float] = None


class RiskProfile(BaseModel):
    aha_prevent_10yr_score: Optional[float] = None
    nhanes_percentile: Optional[float] = None
    risk_category: Optional[str] = None


class DigitalTwinContext(BaseModel):
    """Snapshot of the patient data the assistant bot is allowed to see.

    Always built server-side from the database on each incoming message;
    never accepted from clients (a client must not be able to feed
    fabricated health data to the bot).
    """
    user_id: str
    age: Optional[int] = None
    sex: Optional[str] = None
    smoking_status: Optional[str] = None
    lab_anchors: Optional[LabAnchors] = None
    wearables_summary: Optional[WearablesSummary] = None
    risk_profile: Optional[RiskProfile] = None


class ChatHistoryItem(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    """Payload sent to MeSquareAssistantBot. Constructed by the backend only."""
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    query: str
    twin_context: DigitalTwinContext
    history: list[ChatHistoryItem]


class ChatMessageCreate(BaseModel):
    """Client body for posting a message to a conversation."""
    query: str = Field(min_length=1, max_length=4000)
    client_message_id: Optional[uuid.UUID] = Field(
        default=None,
        description=(
            "Optional idempotency key; reusing one returns 409 instead of "
            "duplicating the message."
        ),
    )

    model_config = ConfigDict(extra="forbid")


class ConversationCreate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)

    model_config = ConfigDict(extra="forbid")


class ConversationResponse(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CitationResponse(BaseModel):
    id: uuid.UUID
    guideline_source: str
    section_reference: Optional[str] = None
    excerpt: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_type: str
    content: str
    twin_snapshot: Optional[dict[str, Any]] = None
    created_at: datetime
    citations: list[CitationResponse] = []

    model_config = ConfigDict(from_attributes=True)


class MessagePage(BaseModel):
    """One page of message history (chronological order) plus the cursor for
    the next older page (keyset pagination)."""
    messages: list[MessageResponse]
    next_before_id: Optional[uuid.UUID] = None


class StreamEvent(BaseModel):
    """Wire format of every SSE event forwarded to the frontend."""
    event: Literal["status", "token", "citation", "done", "error"]
    data: str  # JSON serialization of the event-type-specific payload
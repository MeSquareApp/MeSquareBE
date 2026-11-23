"""Live contract test: call the real MeSquareAssistantBot through our backend's
own SSE client (app/services/assistant_bot.py) with the exact payload shape our
chat route builds. Uses an emergency query so no LLM key or database is needed.

Usage:
    .venv/bin/python tools/live_contract_test.py
"""

import asyncio
import os

os.environ.setdefault("ASSISTANT_BOT_URL", "http://127.0.0.1:8001/internal/v1/chat/stream")

from app.services.assistant_bot import stream_assistant_bot  # noqa: E402

# Payload shaped exactly as our chat route builds it (ChatRequest.model_dump(mode="json"))
payload = {
    "conversation_id": "123e4567-e89b-12d3-a456-426614174000",
    "message_id": "123e4567-e89b-12d3-a456-426614174111",
    "query": "I have sudden severe chest pain and shortness of breath",
    "twin_context": {
        "user_id": "123e4567-e89b-12d3-a456-426614174999",
        "age": 36,
        "sex": "female",
        "smoking_status": None,
        "lab_anchors": {
            "total_cholesterol": 245.0,
            "hdl": 42.0,
            "ldl": 168.0,
            "systolic_bp": 138.0,
            "diastolic_bp": 88.0,
            "fasting_glucose": None,
            "hba1c": None,
            "anchor_date": "2026-11-01",
        },
        "wearables_summary": {
            "resting_heart_rate_avg_14d": 74.0,
            "step_count_avg_14d": 4800.0,
            "sleep_hours_avg_14d": 6.2,
        },
        "risk_profile": {
            "aha_prevent_10yr_score": 8.4,
            "nhanes_percentile": 65.0,
            "risk_category": "borderline",
        },
    },
    "history": [
        {"role": "user", "content": "What was my LDL last time?"},
        {"role": "assistant", "content": "Your latest LDL was 168 mg/dL."},
    ],
}


async def main() -> None:
    print("=== SSE events received by our backend client ===")
    async for event, data in stream_assistant_bot(payload):
        print(f"event={event!r:20} data={data}")
        if event == "done":
            break


if __name__ == "__main__":
    asyncio.run(main())

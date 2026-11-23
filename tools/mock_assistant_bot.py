"""A tiny mock of MeSquareAssistantBot for local testing of the chat endpoints.

Run it in a second terminal next to the API:

    uv run python tools/mock_assistant_bot.py

It listens on port 8001 (the default ASSISTANT_BOT_URL), accepts the
ChatRequest payload, and replies with a canned SSE stream including a
citation and (when the query mentions "aspirin") a guardrail status, so you
can exercise every persistence path in the backend.
"""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class BotHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")

        # Mirrors the real bot's SSE contract: token events, one citations
        # event with a {"citations": [...]} wrapper, then done. Queries
        # matching the guardrail patterns get the early-exit status + done.
        events: list[tuple[str, dict]] = [
            ("token", {"token": "Based on your twin context, "}),
            ("token", {"token": "your 14-day averages look stable."}),
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
        ]
        query = payload.get("query", "").lower()
        if "aspirin" in query or "lipitor" in query:
            events = [
                (
                    "status",
                    {
                        "status": "medication_prohibited",
                        "output_text": "I cannot provide medication advice.",
                    },
                ),
                ("done", {"status": "medication_prohibited", "total_citations": 0}),
            ]
        elif any(
            keyword in query
            for keyword in ("chest pain", "short of breath", "heart attack", "stroke")
        ):
            events = [
                (
                    "status",
                    {
                        "status": "emergency",
                        "output_text": "EMERGENCY NOTICE: Please call 911 immediately.",
                    },
                ),
                ("done", {"status": "emergency", "total_citations": 0}),
            ]
        else:
            events.append(("done", {"status": "success"}))

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for event, data in events:
            self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
        self.wfile.flush()
        # Echo what the backend sent us, so you can inspect the twin context.
        print(f"\n--- ChatRequest received ---\n{json.dumps(payload, indent=2)}\n")

    def log_message(self, format, *args):  # silence default request logging
        pass


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 8001), BotHandler)
    print("Mock assistant bot listening on http://127.0.0.1:8001/chat/stream")
    server.serve_forever()

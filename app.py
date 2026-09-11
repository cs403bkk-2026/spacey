import os

from flask import Flask, jsonify, request

SPACES = [
    {"id": 1, "name": "Founders Desk", "capacity": 1},
]

# In-memory bookings, same pattern as SPACES: prove the reservation flow 
# works end to end before deciding on a real database. Payment is mocked 
# (always succeeds) since we don't have a real payment provider yet.
BOOKINGS = []

def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return "<h1>Startup app</h1><p>The founding team is building here.</p>"

    @app.get("/health")
    def health():
        return jsonify(
            status="ok",
            revision=os.getenv("APP_REVISION", "local"),
        )

    @app.get("/spaces")
    def list_spaces():
        return jsonify(spaces=SPACES)

    @app.post("/spaces/<int:space_id>/bookings")
    def create_booking(space_id):
        space = next((s for s in SPACES if s["id"] == space_id), None)
        if space is None:
            return jsonify(error="space not found"), 404

        body = request.get_json(silent=True) or {}
        member = body.get("member", "guest")

        booking = {
            "id": len(BOOKINGS) + 1,
            "space_id": space_id,
            "member": member,
            "paid": True,  # mocked payment: always succeeds for now
        }
        BOOKINGS.append(booking)
        return jsonify(booking), 201

    return app


app = create_app()

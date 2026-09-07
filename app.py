import os

from flask import Flask, jsonify

SPACES = [
    {"id": 1, "name": "Founders Desk", "capacity": 1},
]

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

    return app


app = create_app()

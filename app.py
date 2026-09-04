import os

from flask import Flask, jsonify


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

    return app


app = create_app()

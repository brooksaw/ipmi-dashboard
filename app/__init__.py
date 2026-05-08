"""Flask application factory."""

import logging

from flask import Flask

from .config import DATABASE_URL
from .poller import init_db, start_poller


def create_app() -> Flask:
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["DATABASE_URL"] = DATABASE_URL

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    from .routes.api import api as api_bp
    from .routes.dashboard import dash as dash_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(dash_bp)

    init_db(DATABASE_URL)
    start_poller(DATABASE_URL)

    return app

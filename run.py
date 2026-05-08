"""Entry point - runs the IPMI dashboard Flask app."""

from app import create_app
from app.config import WEB_PORT

if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False)

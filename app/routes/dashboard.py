"""Dashboard blueprint — serves the single-page UI."""

from flask import Blueprint, render_template

from ..config import SERVERS
from ..disks import ENABLED as DISKS_ENABLED

dash = Blueprint("dash", __name__)


@dash.get("/")
def index():
    server_list = [
        {"id": sid, **cfg} for sid, cfg in SERVERS.items()
    ]
    return render_template(
        "index.html",
        servers=server_list,
        disks_enabled=DISKS_ENABLED,
    )

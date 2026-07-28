"""V9 system and migration-status routes."""
from flask import Blueprint, jsonify

system_bp = Blueprint("system_v9", __name__)


@system_bp.get("/v9/status")
def v9_status():
    return jsonify({
        "status": "ok",
        "version": "9.0",
        "architecture": "modular-foundation",
        "runtime": "compatibility-first",
        "modules": [
            "config",
            "models",
            "routes",
            "services",
            "templates",
            "static",
        ],
    })

"""V9 system and migration-status routes."""
from flask import Blueprint, jsonify

system_bp = Blueprint("system_v9", __name__)


@system_bp.get("/v9/status")
def v9_status():
    return jsonify({
        "status": "ok",
        "version": "9.6",
        "architecture": "modular-foundation-v9.6",
        "runtime": "compatibility-first",
        "modules": [
            "config",
            "models",
            "routes",
            "services",
            "templates",
            "static",
            "business-dashboard",
            "finance-ledger",
            "ai-content-assistant",
            "one-click-social-pack",
            "weekly-content-planner",
            "planner-to-draft",
            "monthly-content-calendar",
            "drag-drop-scheduling",
            "workflow-status-management",
            "operations-dashboard",
            "performance-analytics",
            "evidence-based-recommendations",
            "safe-system-diagnostics",
            "approval-only-social-assistant",
            "comment-dm-classification",
            "three-reply-drafts",
        ],
    })

"""MI Creator Hub application factory."""
from flask import Flask


def create_app() -> Flask:
    # Compatibility-first migration:
    # the verified production app remains the runtime source of truth.
    from .legacy_app import app

    # Register V9-only modular diagnostics.
    from .routes.system import system_bp
    if "system_v9" not in app.blueprints:
        app.register_blueprint(system_bp)

    return app

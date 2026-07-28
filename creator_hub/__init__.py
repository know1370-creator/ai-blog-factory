"""MI Creator Hub application factory."""
from flask import Flask


def create_app() -> Flask:
    from .legacy_app import app, db

    from .routes.system import system_bp
    if "system_v9" not in app.blueprints:
        app.register_blueprint(system_bp)

    from .routes.business import business_bp
    if "business_v91" not in app.blueprints:
        app.register_blueprint(business_bp)

    from .routes.assistant import assistant_bp
    if "assistant_v92" not in app.blueprints:
        app.register_blueprint(assistant_bp)

    from .routes.planner import planner_bp
    if "planner_v93" not in app.blueprints:
        app.register_blueprint(planner_bp)

    with app.app_context():
        db.create_all()

    return app

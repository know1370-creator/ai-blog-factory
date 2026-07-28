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

    with app.app_context():
        db.create_all()

    return app

"""
Render/Gunicorn entry point.

V9.0 keeps the verified V8 application running while the codebase is migrated
into separate modules. Render can continue to use: gunicorn app:app
"""
from creator_hub import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

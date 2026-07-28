# MI Creator Hub V9.0

V9.0 is a compatibility-first modular migration of the verified V8.0 app.

## Deploy on Render

1. Upload all files and folders to the repository root.
2. Keep the start command as `gunicorn app:app`.
3. Preserve the existing Render environment variables and database.
4. Deploy.
5. Check:
   - `/health` → version 9.0
   - `/v9/status` → modular-foundation status

## Why compatibility-first?

A full one-step rewrite can accidentally break Blogger OAuth, publishing,
database migrations, scheduling, or existing article records. V9.0 therefore
keeps the tested application running in `creator_hub/legacy_app.py`, while
introducing stable module boundaries for services, models, configuration,
routes, templates, and static files.

The next extraction steps can move one feature at a time:
1. Dashboard and analytics
2. AI writer and ideas
3. Blogger and scheduling
4. Monetization
5. Templates and static assets

## Project structure

```text
app.py
creator_hub/
  __init__.py
  config.py
  extensions.py
  models.py
  legacy_app.py
  routes/
    system.py
  services/
    ai_service.py
    seo_service.py
    blogger_service.py
    affiliate_service.py
    analytics_service.py
  templates/
  static/
requirements.txt
Procfile
render.yaml
.env.example
```

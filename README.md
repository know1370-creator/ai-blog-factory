# MI Creator Hub V9.3

V9.3 adds a weekly AI content planner while preserving all existing V9.2 features.

## New features

- Weekly planner screen: `/planner/`
- Generates seven days of content ideas from one weekly theme
- Mixes blog, Instagram comic, Reels/Shorts, Threads, and shopping content
- Saves title, hook, content angle, CTA, date, brand, and status
- Converts only selected ideas into full blog and social drafts
- Keeps external publishing under user approval
- Existing AI assistant: `/assistant/`
- Existing finance dashboard: `/business/`

## Deployment

Upload the extracted files and folders to the existing GitHub repository without deleting existing files, Render environment variables, or the database.

Render command:

```text
gunicorn app:app
```

Verify:

- `/health` → version 9.3
- `/v9/status` → modular-foundation-v9.3
- `/planner/` → weekly content planner
- `/assistant/` and `/business/` remain available

The new `weekly_plan_item` database table is created automatically.

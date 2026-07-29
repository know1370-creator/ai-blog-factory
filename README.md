# MI Creator Hub V11.0

V11.0 adds the central content library and series manager.

## New route

- `/library/`

## Features

- Store a complete content project in one record
- Brand, category, content type, and workflow status
- Series name and episode number
- Automatic next episode number for new projects
- Full-text-style search across title, summary, hook, tags, scripts, captions, and drafts
- Filters by brand, category, format, status, and favorite
- Favorite projects
- Duplicate a project to create the next variation or episode
- Store:
  - Instagram comic plan
  - Reel/Shorts script
  - Blog draft
  - Instagram caption
  - Threads text
  - CTA
  - Tags
  - Reference or published URL
- Link an existing Article record
- Bulk-import existing blog articles that are not yet in the library
- Series overview with project count and latest EP number

## Data integrity

- No products, links, prices, metrics, or episode history are invented.
- Episode numbers are calculated only from saved projects.
- Existing articles are imported from the app database.
- Import does not delete or overwrite the original Article record.

## Deployment

Extract the ZIP and overwrite the existing repository files.
Do not delete the database or Render environment variables.

## Verification

- `/health` returns `11.0`
- `/v9/status` returns `modular-foundation-v11.0`
- `/library/` opens
- `/library/create` opens
- `/library/import-articles` opens
- `/diagnostics/` shows the content library table

The new `content_library_item` table is created automatically.

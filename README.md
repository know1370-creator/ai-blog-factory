# MI Creator Hub V9.5

V9.5 adds manual content performance analytics and a safe system diagnostics page.

## New screens

- `/analytics/`
  - Record views, likes, comments, saves, shares, clicks, and revenue
  - Compare channel performance
  - Receive recommendations based only on entered data
  - Delete incorrect records

- `/diagnostics/`
  - Database connection check
  - Required table checks
  - Environment-variable presence checks
  - Secret values are never displayed
  - No OpenAI request is made, so the check does not create API cost

## Deployment

Upload the extracted files over the existing GitHub repository.
Do not delete the database or Render environment variables.

## Verification

- `/health` returns version `9.5`
- `/v9/status` returns `modular-foundation-v9.5`
- `/analytics/` opens normally
- `/diagnostics/` opens normally
- `/calendar/` remains available

The new `content_metric` table is created automatically.

# MI Creator Hub V14.0

V14.0 adds a practical marketing operations layer to V13.0.

## New routes

- `/marketing/` AI Marketing Center
- `/marketing/ideas` Content Idea Bank
- `/marketing/shooting` Shooting Checklist
- `/marketing/monthly-report` Monthly Operations Report

## Marketing Center

The dashboard compares real, manually stored performance data by:

- date range
- brand
- channel
- content
- views
- engagement rate
- save rate
- click rate
- linked revenue

Recommendations are generated deterministically from stored metrics. The system does not invent views, sales, revenue, reach, or growth.

## Idea Bank

- Save an idea, hook, angle, tags, brand, format, category, and priority
- Move ideas through statuses
- Convert an idea into a content-library project
- No automatic content generation or publishing

## Shooting Checklist

Each active content-library project can track:

- location
- props
- cast and outfit
- script
- filming
- editing
- thumbnail
- caption and CTA

## Monthly Report

The monthly report summarizes:

- new content
- completed content
- completion rate
- active projects
- new ideas
- stored performance totals
- brand-level performance

## Database

V14 adds:

- `marketing_idea`
- `shooting_checklist`

Existing tables are not altered.

## Safety

- Only stored performance data is analyzed.
- No automatic posting occurs.
- Affiliate products, links, prices, and discounts are never invented.
- External actions remain approval-only.

## Verification

- `/health` returns `14.0`
- `/v9/status` returns `modular-foundation-v14.0`
- `/marketing/`
- `/marketing/ideas`
- `/marketing/shooting`
- `/marketing/monthly-report`
- `/diagnostics/`

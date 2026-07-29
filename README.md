# MI Creator Hub V10.0

V10 turns MI Creator Hub into a daily AI content manager.

## New routes

- `/manager/`
  - Daily operating brief
  - Today's planner items
  - Open social-reply workload
  - Recent performance hint
  - Recent hook, reel, and experiment activity

- `/manager/hooks`
  - Generates 20 hooks per topic
  - 5 view hooks
  - 5 save hooks
  - 5 comment hooks
  - 5 sales hooks

- `/manager/reels`
  - Reel title and opening hook
  - Second-by-second shooting table
  - Camera direction
  - Action, dialogue, subtitles
  - Props, edit notes, caption, and CTA

- `/manager/experiments`
  - Create A/B content experiments
  - Record views, reactions, and clicks
  - Compare variants using the same weighted formula
  - Mark experiments complete

## Data integrity

- AI does not invent product names, prices, or performance results.
- A/B results use only numbers entered by the user.
- Recent recommendations use only saved performance records.
- Affiliate products and prices are never fabricated.

## Deployment

Extract the ZIP and overwrite the existing repository files.
Do not delete the database or Render environment variables.

## Verification

- `/health` returns version `10.0`
- `/v9/status` returns `modular-foundation-v10.0`
- `/manager/` opens
- `/manager/hooks` opens
- `/manager/reels` opens
- `/manager/experiments` opens
- `/diagnostics/` shows all three V10 tables

The new tables are created automatically:

- `hook_pack`
- `reel_plan`
- `ab_experiment`

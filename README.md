# MI Creator Hub V15.0

V15.0 adds a multi-format Content Factory on top of the V14 marketing center.

## New routes

- `/factory/` Content Factory dashboard
- `/factory/create` New content package
- `/factory/templates` Reusable brand templates
- `/factory/series` Series memory
- `/factory/projects/<id>` Package progress and outputs
- `/factory/outputs/<id>/edit` Output editor

## Content Factory

A single source project can create linked working drafts for:

- Blog
- Reels and Shorts
- Instagram comic
- Threads
- Instagram caption
- Newsletter

Each package stores:

- source text
- brand
- category
- series name
- episode number
- target formats
- character and world notes
- continuity notes
- next-episode hints

## Series memory

- Automatic next episode numbering
- Series-level continuity notes
- Character and world memory
- Latest next-episode hint
- Series overview

## Templates

Reusable templates store:

- brand
- tone
- audience
- hook formula
- content structure
- CTA formula
- safety notes
- favorite status

## Progress tracking

Each package tracks:

- planning
- script
- filming
- editing
- review
- publishing

The completion percentage is calculated from these six saved stages.

## Library workflow

Each factory output can be saved to the existing Content Library in `검토` status.
No content is automatically published.

## Safety

- Drafts do not invent product names, prices, discounts, affiliate links, experiences, statistics, income, or performance.
- User-entered source facts remain the authority.
- Insurance and product wording still require manual review.
- External publishing remains manual and approval-only.

## Database

V15 adds:

- `content_factory_project`
- `content_factory_output`
- `content_factory_template`

Existing tables are not altered.

## Verification

- `/health` returns `15.0`
- `/v9/status` returns `modular-foundation-v15.0`
- `/factory/`
- `/factory/create`
- `/factory/templates`
- `/factory/series`
- `/diagnostics/`

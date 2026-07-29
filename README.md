# MI Creator Hub V13.0

V13.0 adds a content operations pipeline built on top of the V12 project generator and V11 library.

## New routes

- `/pipeline/` drag-and-drop Kanban board
- `/pipeline/brief` daily operations brief
- `/pipeline/items/<id>/settings` priority, deadline, status, and work-note settings

## Pipeline stages

- 기획
- 제작 중
- 검토
- 예약
- 게시 완료
- 보류

## Features

- Drag content cards between pipeline stages
- Save status immediately through a JSON endpoint
- Set high, normal, or low priority
- Add a deadline or internal publishing date
- Add private work notes
- Show progress by workflow stage
- Highlight overdue and due-today work
- Produce a daily priority brief using only saved status, priority, and deadline data
- Show projects due within seven days
- Filter the board by brand or title
- Open each card in the existing content library

## Data integrity and safety

- No performance, audience, revenue, or publishing result is fabricated.
- Daily priorities are deterministic recommendations based only on saved project data.
- The `예약` stage is internal workflow management only.
- Moving a card never posts content to an external service.
- External messages and publishing remain manual approval actions.

## Database

V13 adds one table:

- `pipeline_meta`

It stores:

- library item reference
- priority
- due date
- scheduled timestamp
- owner note

The existing content library table is not changed, avoiding an unsafe production column migration.

## Deployment

Extract the ZIP and overwrite the existing repository.
Keep the current database and Render environment variables.

## Verification

- `/health` returns `13.0`
- `/v9/status` returns `modular-foundation-v13.0`
- `/pipeline/` opens
- `/pipeline/brief` opens
- `/diagnostics/` shows the pipeline settings table

# MI Creator Hub V9.4

V9.4 adds a monthly content calendar, drag-and-drop date changes, workflow status management, scheduling preparation, and an operations dashboard.

## New in V9.4

- Monthly content calendar: `/calendar/`
- Drag and drop a content card onto another date
- Workflow statuses:
  - 기획
  - 초안
  - 검토
  - 예약
  - 발행완료
- Reservation date and time saved to the related article
- Reservation requires an existing AI draft
- External publishing still requires user review and approval
- Operations dashboard: `/calendar/operations`
- Calendar summary:
  - today schedule count
  - review queue
  - reservations
  - published items
  - current month revenue

## Existing screens

- `/planner/`
- `/assistant/`
- `/business/`
- `/calendar/`

## Deployment

Extract the ZIP and upload its files and folders over the existing GitHub repository.
Do not delete the database or Render environment variables.

Render command:

```text
gunicorn app:app
```

## Verification

- `/health` returns version `9.4`
- `/v9/status` returns `modular-foundation-v9.4`
- `/calendar/` opens the monthly calendar
- `/calendar/operations` opens the operations dashboard
- Existing V9.1 to V9.3 screens remain available

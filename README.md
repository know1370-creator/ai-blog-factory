# MI Creator Hub V9.4.1 Hotfix

This patch fixes the `/calendar/` internal server error.

## Cause

The calendar attempted to filter finance records using `FinanceEntry.entry_type`,
but the V9.1 finance model stores income and cost types in the `category` column.

## Fix

Monthly revenue now filters by the existing income categories:

- adsense
- coupang
- atomy
- other_income

## Deployment

Upload the extracted files over the existing GitHub repository.
Do not delete the database or Render environment variables.

Verify:

- `/health` returns version `9.4.1`
- `/calendar/` opens normally
- `/business/` remains available

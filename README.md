# MI Creator Hub V9.1

V9.1 adds a practical revenue and ROI dashboard while preserving all V9.0 features.

## New features

- Monthly revenue dashboard
- AdSense, Coupang, Atomy, and other-income entries
- OpenAI, hosting, and other-cost entries
- Monthly net profit calculation
- Average operating cost per generated article
- Recent finance-entry history and deletion
- New route: `/business/`

## Safe deployment

Upload the project files to the existing repository and deploy the latest commit.
Keep the existing Render environment variables and database.

Render start command:

```text
gunicorn app:app
```

Check after deployment:

- `/health` should show version `9.1`
- `/v9/status` should show `modular-foundation-v9.1`
- `/business/` should open the new dashboard

The `finance_entry` table is created automatically. Existing article and Blogger data are not deleted.

# MI Creator Hub V9.2

V9.2 adds the AI Content Assistant while preserving V9.1 revenue features and all existing Blogger functionality.

## New in V9.2

- New AI Content Assistant screen at `/assistant/`
- One topic creates:
  - Blog title, meta description, HTML article, and tags
  - SEO analysis
  - Instagram caption with CTA and hashtags
  - Threads post
  - Reels/Shorts script with hook, scenes, subtitles, and CTA
- Brand presets:
  - 말썽쟁이 딸랑구
  - 미우와 웅이
  - 보험·재무
  - 애터미·생활용품
  - 쿠팡·쇼핑
- Recent content list and pipeline progress
- Thumbnail generation remains optional to avoid unnecessary image-generation cost

## Deployment

Upload all extracted files and folders to the existing GitHub repository without deleting the database or Render environment variables.

Render start command:

```text
gunicorn app:app
```

Verify after deployment:

- `/health` shows version `9.2`
- `/v9/status` shows `modular-foundation-v9.2`
- `/assistant/` opens the AI Content Assistant
- `/business/` still opens the V9.1 revenue dashboard

Existing articles, Blogger connections, scheduled posts, and finance entries are preserved.

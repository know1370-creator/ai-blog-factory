# MI Creator Hub V12.0

V12.0 adds a one-click multi-channel content project generator.

## New route

- `/generator/`

## One AI request creates

- An 8-cut Instagram comic plan
- A 20–35 second Reel/Shorts shooting plan
- A blog title, meta description, and HTML draft
- An Instagram caption
- A Threads post
- A CTA
- Hashtags
- Shooting props
- Three thumbnail-text ideas
- A safety and fact-check note

## Storage workflow

1. The generated package is saved as one `ContentLibraryItem`.
2. If selected, the blog and social copy are also saved to the existing `Article` model.
3. A series name automatically receives the next episode number from saved data.
4. The project starts in `검토` status.
5. Nothing is automatically posted outside the app.

## Safety and affiliate integrity

- The generator does not invent product names, prices, discounts, affiliate links, experiences, statistics, income, or performance.
- Product and affiliate details are used only when the user supplies them.
- Insurance and finance content avoids guarantees and reminds users that conditions may vary.
- External posting always remains a manual approval step.

## Deployment

Extract the ZIP and overwrite the existing repository files.
Keep the existing database and Render environment variables.

## Verification

- `/health` returns `12.0`
- `/v9/status` returns `modular-foundation-v12.0`
- `/generator/` opens
- `/library/` opens
- `/diagnostics/` opens

The generator uses the existing `OPENAI_API_KEY`.

# MI Creator Hub V9.6

V9.6 adds an approval-only AI engagement assistant.

## New screen

- `/social/`

## Features

- Manually register Instagram, Threads, YouTube, or blog comments and inquiries
- Basic local classification without API cost
- AI classification into purchase inquiry, collaboration, question, compliment, complaint, spam, or general
- Priority marking for messages that should be answered first
- Generate three Korean reply drafts
- Select or edit a reply
- Explicit approval step
- Mark as completed after the user manually posts the reply
- Filter inbox by workflow status

## Safety design

- No automatic likes
- No automatic comments
- No unofficial login automation
- No social-media password storage
- No reply is externally posted in V9.6
- The user remains in control of every external message

## Deployment

Extract the ZIP and overwrite the existing repository files.
Do not delete the database or Render environment variables.

## Verification

- `/health` returns version `9.6`
- `/v9/status` returns `modular-foundation-v9.6`
- `/social/` opens normally
- `/diagnostics/` shows the social assistant table as available

The new `social_interaction` table is created automatically.

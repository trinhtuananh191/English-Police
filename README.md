# English Police Bot (v2)

A Discord bot that automatically corrects grammar, suggests natural rewrites, tracks vocabulary, and reports daily progress — powered by OpenAI (gpt-4o-mini). Built to respect casual/Gen-Z writing style: slang, abbreviations, and lowercase texting are NOT flagged as errors. Only real grammar mistakes are.

## Features
- **Auto grammar check** in your designated channel — reacts ✅ if clean, ✏️ + a thread with corrections if not.
- **Natural rewrite suggestions** — more native-sounding phrasing, keeping your casual tone.
- **Style-aware**: ignores abbreviations (abt, u, rn, gonna...), lowercase sentence starts, casually-lowercased names/places, and intentional slang/Gen-Z expressions.
- **Vocabulary tracker** — automatically saves new words/phrases the bot notices in your messages.
- **Daily stats report** — posted automatically every day in `#daily-report`: message count, error rate, new vocab learned per person.
- **CEFR level estimate** — updated daily based on recent messages, check yours with `!level`.

## Commands
- `!level` — show your latest estimated CEFR level
- `!report` — manually trigger today's report (for testing)

## Required Environment Variables (set in Railway)
- `DISCORD_BOT_TOKEN` — from Discord Developer Portal
- `OPENAI_API_KEY` — from platform.openai.com
- `DATABASE_URL` — automatically provided by Railway once you attach a PostgreSQL database to the project (no manual setup needed)
- `TARGET_CHANNEL_NAME` — (optional) channel the bot checks grammar in, default `chat-en`
- `REPORT_CHANNEL_NAME` — (optional) channel for daily reports, default `daily-report`
- `REPORT_HOUR_UTC` — (optional) UTC hour (0-23) to send the daily report, default `15` (which is 22:00 / 10 PM Vietnam time)

## Setup notes
1. In your Discord server, create two channels: `chat-en` (or your custom name) and `daily-report`.
2. In Railway, click **"New"** → **"Database"** → **"Add PostgreSQL"** to attach a database to this project. Railway will automatically inject `DATABASE_URL` into your bot's environment variables — you don't need to set it manually.
3. Make sure "Message Content Intent" is enabled in the Discord Developer Portal (under the Bot section).
4. Deploy as usual — the bot will auto-create its database tables on first run.

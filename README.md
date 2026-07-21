# English Police Bot (v2)

A Discord bot that automatically corrects grammar, suggests natural rewrites, tracks vocabulary, and reports daily progress — powered by OpenAI (gpt-4o-mini). Built to respect casual/Gen-Z writing style: slang, abbreviations, and lowercase texting are NOT flagged as errors. Only real grammar mistakes are.

## Features
- **Auto grammar check** in your designated channel — reacts ✅ if clean, ✏️ + a thread with corrections if not.
- **Natural rewrite suggestions** — more native-sounding phrasing, keeping your casual tone.
- **Style-aware**: ignores abbreviations (abt, u, rn, gonna...), lowercase sentence starts, casually-lowercased names/places, and intentional slang/Gen-Z expressions.
- **Vocabulary tracker** — automatically saves new words/phrases the bot notices in your messages.
- **Vocab drops** — posts AI-generated vocabulary batches in `#vocab-drop`.
- **Daily news briefing** — posts GNews-based Tech/AI/Design/Dev article summaries in `#daily-news` at 09:00 Vietnam time.
- **Adaptive translation practice** — `/practice` creates a dedicated thread for a Vietnamese-to-English exercise, grades the learner there, and continues with a personalised next round in the same thread.
- **Daily practice prompts** — mentions everyone and creates shared exercise threads at 09:00, 14:00, and 21:00 in the configured practice channel; learners answer inside the thread to receive feedback.
- **Deploy announcement** — automatically announces successful new-feature deploys once per deploy.
- **Daily stats report** — posted automatically every day in `#daily-report`: message count, error rate, new vocab learned per person. Each report covers the last 24 hours so messages after the previous report are not missed.
- **CEFR level estimate** — updated daily based on recent messages, check yours with `!level`.

## Commands
- `!level` — show your latest estimated CEFR level
- `!report` — manually trigger today's report (for testing)
- `!vocab` — manually trigger the current vocab drop window
- `!practice` or `/practice` — start a personalised Vietnamese-to-English translation round
- `!news` or `/news` — manually trigger today's daily news briefing

## Required Environment Variables (set in Railway)
- `DISCORD_BOT_TOKEN` — from Discord Developer Portal
- `OPENAI_API_KEY` — from platform.openai.com
- `GNEWS_API_KEY` — from gnews.io, used for the daily news briefing
- `DATABASE_URL` — automatically provided by Railway once you attach a PostgreSQL database to the project (no manual setup needed)
- `TARGET_CHANNEL_NAME` — (optional) channel the bot checks grammar in, default `chat-en`
- `REPORT_CHANNEL_NAME` — (optional) channel for daily reports, default `daily-report`
- `VOCAB_CHANNEL_NAME` — (optional) channel for vocabulary drops, default `vocab-drop`
- `NEWS_CHANNEL_NAME` — (optional) channel for daily news, default `daily-news`
- `PRACTICE_CHANNEL_NAME` — (optional) channel for scheduled practice, default uses `TARGET_CHANNEL_NAME`
- `PRACTICE_SEND_HOURS_LOCAL` — (optional) comma-separated local hours for practice drops, default `9,14,21`
- `PRACTICE_MODEL` — (optional) OpenAI model used for practice generation and grading, default `gpt-4o-mini`
- `DISCORD_GUILD_ID` — (optional) sync slash commands to one Discord server immediately instead of global sync
- `SYNC_SLASH_COMMANDS` — (optional) set to `false` to disable slash command syncing on startup
- `DEPLOY_ANNOUNCE_CHANNEL_NAME` — (optional) channel for deploy announcements, default uses `TARGET_CHANNEL_NAME`
- `DEPLOY_ANNOUNCEMENT_MESSAGE` — (optional) deploy announcement text, default `Anh vừa học học được kỹ năng mới, mấy con vợ vào test đi`
- `DEPLOY_ANNOUNCE_KEY` — (optional) custom unique key for each deploy if your host does not expose a commit/deployment id
- `DEPLOY_ANNOUNCE_ENABLED` — (optional) set to `false` to disable deploy announcements
- `REPORT_HOUR_UTC` — (optional) UTC hour (0-23) to send the daily report, default `16` (which is 23:00 / 11 PM Vietnam time)
- `APP_TIMEZONE` — (optional) timezone used for daily counters/reports, default `Asia/Ho_Chi_Minh`

## Setup notes
1. In your Discord server, create channels for `chat-en` (or your custom name), `daily-report`, `vocab-drop`, and `daily-news`. Scheduled practice uses `chat-en` by default; set `PRACTICE_CHANNEL_NAME` if you want a separate channel.
2. In Railway, click **"New"** → **"Database"** → **"Add PostgreSQL"** to attach a database to this project. Railway will automatically inject `DATABASE_URL` into your bot's environment variables — you don't need to set it manually.
3. Make sure "Message Content Intent" is enabled in the Discord Developer Portal (under the Bot section). Grant the bot **Mention Everyone**, **Create Public Threads**, and **Send Messages in Threads** permissions for the practice channel.
4. Deploy as usual — the bot will auto-create its database tables on first run.
5. No command is needed for deploy announcements. When a new deploy starts successfully, the bot posts the configured message once for that deploy. Railway provides `RAILWAY_DEPLOYMENT_ID` automatically, so `DEPLOY_ANNOUNCE_KEY` is only needed on hosts without a deploy/commit id.
6. Use `/news` to manually trigger the news briefing. Global slash commands can take time to appear; set `DISCORD_GUILD_ID` for immediate server-level sync during testing.
7. Run `/practice` in the main practice channel, then answer inside the thread created by the bot. Scheduled prompts also have their own thread; messages in the main channel are never consumed as practice answers.

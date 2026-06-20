# English Buddy Bot

A Discord bot that automatically corrects grammar and suggests more natural phrasing, powered by the OpenAI API (gpt-4o-mini).

## How it works
- The bot listens to messages in a channel named `chat-en` (rename this channel in Discord, or change the `TARGET_CHANNEL_NAME` variable if you want to use a different name).
- If the sentence is correct -> the bot reacts with ✅
- If the sentence has an error -> the bot reacts with ✏️ and creates a separate thread on that message, sending the correction + a more natural rewrite suggestion + a short explanation.

## Required Environment Variables (set these in Railway)
- `DISCORD_BOT_TOKEN` — token from the Discord Developer Portal
- `OPENAI_API_KEY` — key from platform.openai.com
- `TARGET_CHANNEL_NAME` — (optional) the channel name the bot will operate in, defaults to `chat-en`

## Important
- In your Discord server, create a channel named exactly `chat-en` (or whatever name you set in `TARGET_CHANNEL_NAME`).
- Make sure "Message Content Intent" is enabled in the Discord Developer Portal (under the Bot section).

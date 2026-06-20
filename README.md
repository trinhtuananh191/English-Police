# English Buddy Bot

A Discord bot that checks English grammar with OpenAI. The original automatic channel flow and `!strictness` command are retained. A `/check` fallback is also available without privileged Discord intents.

## Automatic mode (default)

The bot automatically checks every message in `chat-en` (or the channel configured
with `TARGET_CHANNEL_NAME`). No command is required.

- Correct sentence → reacts with ✅
- Sentence with an error → reacts with ✏️, creates a thread, and posts the correction there

Automatic mode requires **Message Content Intent** in Discord Developer Portal →
Bot → Privileged Gateway Intents.

You can also check a sentence manually with:

```text
/check text: I goes to school every day
```

The result is public in the channel. Correct sentences receive a ✅ response;
sentences with errors receive a ✏️ response and a correction thread. If the bot
does not have permission to create a thread, it posts the correction directly.

Available slash commands:

- `/check text: ...` — check an English sentence
- `/help` — show usage and current automatic-mode status
- `/strictness` — placeholder for the upcoming strictness setting

## Configuration

`AUTO_CHECK_ENABLED` defaults to `true`. Set it to `false` only if you want to
disable automatic checking and use slash commands exclusively.

- Correct sentence → reacts with ✅
- Sentence with an error → reacts with ✏️ and creates a correction thread
- The original `!strictness` placeholder command remains available

If Discord reports `PrivilegedIntentsRequired`, remove `AUTO_CHECK_ENABLED` or set it to `false`, then redeploy. `/check` will continue to work.

Discord requires Message Content Intent for both automatic message checking and prefix commands such as `!strictness`; this restriction cannot be bypassed in application code.

The bot syncs slash commands globally and directly to every server it joins so they appear immediately. If slash commands are still missing, reinstall the application with both `bot` and `applications.commands` OAuth2 scopes.

## Railway environment variables

- `DISCORD_BOT_TOKEN` — required; token from Discord Developer Portal → Bot
- `OPENAI_API_KEY` — required; OpenAI project API key
- `TARGET_CHANNEL_NAME` — optional; defaults to `chat-en`
- `AUTO_CHECK_ENABLED` — optional; defaults to `true`

After changing a variable, redeploy the Railway service. Do not add quotes or a `Bot ` prefix around the Discord token.

## Discord installation permissions

Install the application with the `bot` and `applications.commands` scopes. Automatic mode additionally needs permission to view the channel, read message history, add reactions, create public threads, and send messages in threads.

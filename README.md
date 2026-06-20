# English Buddy Bot

A Discord bot that checks English grammar with OpenAI. The original automatic channel flow and `!strictness` command are retained. A `/check` fallback is also available without privileged Discord intents.

## Default mode (recommended)

The bot starts without privileged intents. In Discord, run:

```text
/check text: I goes to school every day
```

The result is sent privately to the person who used the command.

## Optional automatic mode

Set `AUTO_CHECK_ENABLED=true` to listen automatically in `chat-en`. This mode requires **Message Content Intent** to be enabled in Discord Developer Portal → Bot → Privileged Gateway Intents.

- Correct sentence → reacts with ✅
- Sentence with an error → reacts with ✏️ and creates a correction thread
- The original `!strictness` placeholder command remains available

If Discord reports `PrivilegedIntentsRequired`, remove `AUTO_CHECK_ENABLED` or set it to `false`, then redeploy. `/check` will continue to work.

Discord requires Message Content Intent for both automatic message checking and prefix commands such as `!strictness`; this restriction cannot be bypassed in application code.

## Railway environment variables

- `DISCORD_BOT_TOKEN` — required; token from Discord Developer Portal → Bot
- `OPENAI_API_KEY` — required; OpenAI project API key
- `TARGET_CHANNEL_NAME` — optional; defaults to `chat-en`
- `AUTO_CHECK_ENABLED` — optional; defaults to `false`

After changing a variable, redeploy the Railway service. Do not add quotes or a `Bot ` prefix around the Discord token.

## Discord installation permissions

Install the application with the `bot` and `applications.commands` scopes. Automatic mode additionally needs permission to view the channel, read message history, add reactions, create public threads, and send messages in threads.

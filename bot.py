import os
import json
import discord
from discord.ext import commands
from openai import OpenAI

# ====== CONFIG (loaded from Environment Variables on Railway) ======
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# Name of the channel the bot will auto-check grammar in. Change this if your channel has a different name.
TARGET_CHANNEL_NAME = os.getenv("TARGET_CHANNEL_NAME", "chat-en")
# Minimum message length to trigger a check (skips short messages like "ok", "lol")
MIN_LENGTH = 6

# ====== DEBUG: check whether Railway is correctly passing the environment variables ======
print("---- DEBUG ENV CHECK ----")
print(f"DISCORD_BOT_TOKEN exists: {bool(DISCORD_BOT_TOKEN)}, length: {len(DISCORD_BOT_TOKEN) if DISCORD_BOT_TOKEN else 0}")
print(f"DISCORD_BOT_TOKEN starts with: {DISCORD_BOT_TOKEN[:7] if DISCORD_BOT_TOKEN else 'NO VALUE'}")
print(f"DISCORD_BOT_TOKEN ends with: {DISCORD_BOT_TOKEN[-5:] if DISCORD_BOT_TOKEN else 'NO VALUE'}")
print(f"DISCORD_BOT_TOKEN has extra whitespace/newline: {DISCORD_BOT_TOKEN != DISCORD_BOT_TOKEN.strip() if DISCORD_BOT_TOKEN else 'N/A'}")
print(f"DISCORD_BOT_TOKEN has exactly 2 dots (valid token-like format): {DISCORD_BOT_TOKEN.count('.') == 2 if DISCORD_BOT_TOKEN else 'N/A'}")
print("")
print(f"OPENAI_API_KEY exists: {bool(OPENAI_API_KEY)}, length: {len(OPENAI_API_KEY) if OPENAI_API_KEY else 0}")
print(f"OPENAI_API_KEY starts with: {OPENAI_API_KEY[:7] if OPENAI_API_KEY else 'NO VALUE'}")
print(f"OPENAI_API_KEY has extra whitespace/newline: {OPENAI_API_KEY != OPENAI_API_KEY.strip() if OPENAI_API_KEY else 'N/A'}")
print("--------------------------")

client_ai = OpenAI(api_key=OPENAI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

SYSTEM_PROMPT = """You are a friendly, encouraging English teacher helping intermediate learners improve their English through daily chat messages.

Given a message written by a student, do the following:
1. Decide if the sentence has any grammar, spelling, or word-choice errors.
2. If it does, provide a corrected version.
3. Suggest a more natural / native-like way to phrase it, if different from the correction.
4. Give a short, friendly explanation (1-2 sentences max) of the main issue, in simple English.

Respond ONLY in this exact JSON format, with no extra text, no markdown fences:
{
  "has_error": true or false,
  "corrected": "corrected sentence here (empty string if no error)",
  "natural_rewrite": "more natural phrasing here (empty string if same as corrected or no improvement)",
  "explanation": "short friendly explanation here (empty string if no error)"
}

If the message is already correct and natural, set has_error to false and leave the other fields empty.
Do not be overly strict about minor stylistic choices - focus on actual errors and genuinely awkward phrasing.
"""


async def check_grammar(text: str):
    """Call the OpenAI API to check grammar, return the result as a dict."""
    response = client_ai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


@bot.event
async def on_ready():
    print(f"✅ Bot is online: {bot.user}")


@bot.event
async def on_message(message: discord.Message):
    # Ignore the bot's own messages
    if message.author.bot:
        return

    # Only process messages in the target channel
    if message.channel.name != TARGET_CHANNEL_NAME:
        await bot.process_commands(message)
        return

    text = message.content.strip()

    # Skip messages that are too short or just links/emoji
    if len(text) < MIN_LENGTH:
        await bot.process_commands(message)
        return

    try:
        result = await check_grammar(text)
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        await bot.process_commands(message)
        return

    if result is None:
        await bot.process_commands(message)
        return

    if not result.get("has_error"):
        # Sentence is correct -> react with a checkmark, no need to clutter the chat
        try:
            await message.add_reaction("✅")
        except Exception:
            pass
    else:
        # Sentence has an error -> create a separate thread to avoid cluttering the main channel
        try:
            await message.add_reaction("✏️")
            thread = await message.create_thread(
                name=f"Correction for {message.author.display_name}",
                auto_archive_duration=60,
            )
            reply_lines = [f"**Original:** {text}"]
            if result.get("corrected"):
                reply_lines.append(f"**Corrected:** {result['corrected']}")
            if result.get("natural_rewrite") and result["natural_rewrite"] != result.get("corrected"):
                reply_lines.append(f"**More natural phrasing:** {result['natural_rewrite']}")
            if result.get("explanation"):
                reply_lines.append(f"**Explanation:** {result['explanation']}")

            await thread.send("\n".join(reply_lines))
        except Exception as e:
            print(f"Error sending correction: {e}")

    await bot.process_commands(message)


@bot.command(name="strictness")
async def strictness(ctx, level: str = None):
    """Placeholder command for the strictness-level config feature (Phase 2)."""
    await ctx.send("This feature will be added in a future version! 🚧")


if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        raise ValueError("Missing DISCORD_BOT_TOKEN in Environment Variables!")
    if not OPENAI_API_KEY:
        raise ValueError("Missing OPENAI_API_KEY in Environment Variables!")
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except discord.errors.LoginFailure as e:
        print(f"❌ DISCORD LOGIN ERROR: Invalid token. Details: {e}")
    except Exception as e:
        print(f"❌ UNKNOWN ERROR while running the bot: {e}")

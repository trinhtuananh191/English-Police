import os
from datetime import datetime, date, timezone

import discord
from discord.ext import commands, tasks
from openai import OpenAI

import database as db
from grammar import check_grammar
from cefr import estimate_cefr_level
from vocab_scheduler import send_word_batch, SEND_HOURS_UTC

# ====== CONFIG ======
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TARGET_CHANNEL_NAME = os.getenv("TARGET_CHANNEL_NAME", "chat-en")
REPORT_CHANNEL_NAME = os.getenv("REPORT_CHANNEL_NAME", "daily-report")
VOCAB_CHANNEL_NAME = os.getenv("VOCAB_CHANNEL_NAME", "vocab-drop")
REPORT_HOUR_UTC = int(os.getenv("REPORT_HOUR_UTC", "16"))  # 23:00 ICT
MIN_LENGTH = 6

if not DISCORD_BOT_TOKEN:
    raise ValueError("Missing DISCORD_BOT_TOKEN in Environment Variables!")
if not OPENAI_API_KEY:
    raise ValueError("Missing OPENAI_API_KEY in Environment Variables!")

client_ai = OpenAI(api_key=OPENAI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ────────────────────────────────────────────
# STARTUP
# ────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ Bot is online: {bot.user}")
    db.init_db()
    if not clock_task.is_running():
        clock_task.start()


# ────────────────────────────────────────────
# MASTER CLOCK
# ────────────────────────────────────────────

@tasks.loop(minutes=1)
async def clock_task():
    now = datetime.now(timezone.utc)
    h, m = now.hour, now.minute

    if h in SEND_HOURS_UTC and m == 0:
        await send_word_batch(bot, client_ai, VOCAB_CHANNEL_NAME)

    if h == REPORT_HOUR_UTC and m == 0:
        await send_daily_report()


# ────────────────────────────────────────────
# GRAMMAR CHECK
# ────────────────────────────────────────────

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.channel.name != TARGET_CHANNEL_NAME:
        await bot.process_commands(message)
        return

    text = message.content.strip()
    if len(text) < MIN_LENGTH:
        await bot.process_commands(message)
        return

    try:
        result = check_grammar(client_ai, text)
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        await bot.process_commands(message)
        return

    if result is None:
        await bot.process_commands(message)
        return

    discord_id = str(message.author.id)
    username = message.author.display_name
    has_error = bool(result.get("has_error"))
    new_vocab = result.get("new_vocab") or []
    formality_score = result.get("formality_score")

    try:
        db.log_message(
            discord_id=discord_id,
            username=username,
            channel_id=str(message.channel.id),
            original_text=text,
            corrected_text=result.get("corrected", ""),
            natural_rewrite=result.get("natural_rewrite", ""),
            has_error=has_error,
            error_types=result.get("error_types", []),
            formality_score=formality_score,
        )
        for v in new_vocab:
            db.save_vocab(
                discord_id=discord_id,
                username=username,
                word_or_phrase=v.get("word", ""),
                meaning=v.get("meaning", ""),
                example_sentence=v.get("example", ""),
            )
        db.upsert_daily_stat(
            discord_id=discord_id,
            username=username,
            stat_date=date.today(),
            has_error=has_error,
            new_vocab_count=len(new_vocab),
            formality_score=formality_score,
        )
    except Exception as e:
        print(f"Database error: {e}")

    if not has_error:
        try:
            await message.add_reaction("✅")
        except Exception:
            pass
    else:
        try:
            await message.add_reaction("✏️")
            thread = await message.create_thread(
                name=f"Correction for {username}",
                auto_archive_duration=60,
            )
            reply_lines = [f"**Original:** {text}"]
            if result.get("corrected"):
                reply_lines.append(f"**Corrected:** {result['corrected']}")
            if result.get("natural_rewrite") and result["natural_rewrite"] != result.get("corrected"):
                reply_lines.append(f"**More natural:** {result['natural_rewrite']}")
            if result.get("explanation"):
                reply_lines.append(f"**Why:** {result['explanation']}")
            if new_vocab:
                vocab_lines = "\n".join(
                    f"  • **{v.get('word')}** — {v.get('meaning')}" for v in new_vocab
                )
                reply_lines.append(f"**New vocab spotted:**\n{vocab_lines}")

            await thread.send("\n".join(reply_lines))
        except Exception as e:
            print(f"Error sending correction: {e}")

    await bot.process_commands(message)


# ────────────────────────────────────────────
# DAILY REPORT
# ────────────────────────────────────────────

def formality_label(score):
    """Convert a 0.0-1.0 score to a human-readable label."""
    if score is None:
        return "N/A"
    if score < 0.25:
        return f"{round(score * 100)}% — very casual 🤙"
    if score < 0.5:
        return f"{round(score * 100)}% — casual 😊"
    if score < 0.75:
        return f"{round(score * 100)}% — neutral 📝"
    return f"{round(score * 100)}% — formal 🎩"


async def send_daily_report():
    report_channel = discord.utils.get(
        [ch for guild in bot.guilds for ch in guild.text_channels],
        name=REPORT_CHANNEL_NAME,
    )
    if report_channel is None:
        print(f"⚠️ Report channel '#{REPORT_CHANNEL_NAME}' not found.")
        return

    today = date.today()
    stats = db.get_daily_stats(today)

    if not stats:
        await report_channel.send(
            f"📊 **Daily Report — {today.isoformat()}**\n"
            f"No activity today. Let's chat more tomorrow! 💬"
        )
        return

    lines = [f"📊 **Daily Report — {today.isoformat()}**\n"]

    for row in stats:
        username = row["username"]
        total = row["total_messages"]
        correct = row["messages_correct"]
        errors = row["messages_with_errors"]
        vocab = row["new_vocab_count"]
        avg_formality = row.get("avg_formality_score")

        lines.append(
            f"**{username}**\n"
            f"  ✅ Correct sentences: **{correct}**\n"
            f"  ✏️ Incorrect sentences: **{errors}**\n"
            f"  📖 New vocab spotted: **{vocab}** word(s)\n"
            f"  🎭 Writing style: **{formality_label(avg_formality)}**\n"
        )

    await report_channel.send("\n".join(lines))

    # CEFR update
    for row in stats:
        discord_id = row["discord_id"]
        username = row["username"]
        try:
            recent = db.get_recent_messages(discord_id, limit=30)
            cefr_result = estimate_cefr_level(client_ai, recent)
            if cefr_result:
                db.save_cefr_estimate(discord_id, username, cefr_result["level"])
                await report_channel.send(
                    f"📈 **{username}** estimated level: **{cefr_result['level']}** — {cefr_result['summary']}"
                )
        except Exception as e:
            print(f"CEFR estimation error for {username}: {e}")


# ────────────────────────────────────────────
# COMMANDS
# ────────────────────────────────────────────

@bot.command(name="level")
async def level_cmd(ctx):
    """Show your latest estimated CEFR level."""
    row = db.get_latest_cefr(str(ctx.author.id))
    if row is None:
        await ctx.send("No level estimate yet — keep chatting and check back after today's report! 📈")
    else:
        await ctx.send(f"📈 Your latest estimated level: **{row['estimated_level']}**")


@bot.command(name="report")
async def report_cmd(ctx):
    """Manually trigger today's daily report (for testing)."""
    await send_daily_report()
    await ctx.send("Report sent! ✅")


@bot.command(name="vocab")
async def vocab_cmd(ctx):
    """Manually trigger the next vocab drop (for testing)."""
    await send_word_batch(bot, client_ai, VOCAB_CHANNEL_NAME)
    await ctx.send("Vocab drop sent! 📚")


# ────────────────────────────────────────────
# RUN
# ────────────────────────────────────────────

if __name__ == "__main__":
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except discord.errors.LoginFailure as e:
        print(f"❌ DISCORD LOGIN ERROR: {e}")
    except Exception as e:
        print(f"❌ UNKNOWN ERROR: {e}")

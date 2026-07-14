import os
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks
from openai import OpenAI

import database as db
from grammar import check_grammar
from cefr import estimate_cefr_level
from news_scheduler import NEWS_SEND_HOUR_UTC, send_daily_news
from time_utils import APP_TIMEZONE_NAME, as_db_utc_naive, local_date_for, report_window_bounds_utc, today_local
from vocab_scheduler import send_word_batch, SEND_HOURS_UTC

# ====== CONFIG ======
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TARGET_CHANNEL_NAME = os.getenv("TARGET_CHANNEL_NAME", "chat-en")
REPORT_CHANNEL_NAME = os.getenv("REPORT_CHANNEL_NAME", "daily-report")
VOCAB_CHANNEL_NAME = os.getenv("VOCAB_CHANNEL_NAME", "vocab-drop")
NEWS_CHANNEL_NAME = os.getenv("NEWS_CHANNEL_NAME", "daily-news")
DEPLOY_ANNOUNCE_CHANNEL_NAME = os.getenv("DEPLOY_ANNOUNCE_CHANNEL_NAME", TARGET_CHANNEL_NAME)
DEPLOY_ANNOUNCEMENT_MESSAGE = os.getenv(
    "DEPLOY_ANNOUNCEMENT_MESSAGE",
    "Anh vừa học học được kỹ năng mới, mấy con vợ vào test đi",
)
DEPLOY_ANNOUNCE_ENABLED = os.getenv("DEPLOY_ANNOUNCE_ENABLED", "true").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
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
last_auto_report_date = None
deploy_announcement_checked = False
DISCORD_MESSAGE_LIMIT = 2000


# ────────────────────────────────────────────
# STARTUP
# ────────────────────────────────────────────

def get_deploy_announcement_key():
    for env_name in (
        "DEPLOY_ANNOUNCE_KEY",
        "RAILWAY_DEPLOYMENT_ID",
        "RAILWAY_GIT_COMMIT_SHA",
        "RENDER_GIT_COMMIT",
        "VERCEL_GIT_COMMIT_SHA",
        "HEROKU_SLUG_COMMIT",
        "SOURCE_VERSION",
    ):
        value = os.getenv(env_name)
        if value:
            return f"{env_name}:{value}"
    return None


async def send_deploy_announcement_once():
    global deploy_announcement_checked

    if deploy_announcement_checked or not DEPLOY_ANNOUNCE_ENABLED:
        return
    deploy_announcement_checked = True

    deploy_key = get_deploy_announcement_key()
    if not deploy_key:
        print("⚠️ Deploy announcement skipped: no deploy key found. Set DEPLOY_ANNOUNCE_KEY to enable it.")
        return

    announce_channel = discord.utils.get(
        [ch for guild in bot.guilds for ch in guild.text_channels],
        name=DEPLOY_ANNOUNCE_CHANNEL_NAME,
    )
    if announce_channel is None:
        print(f"⚠️ Deploy announcement channel '#{DEPLOY_ANNOUNCE_CHANNEL_NAME}' not found.")
        return

    try:
        should_announce = db.claim_deploy_announcement(deploy_key, DEPLOY_ANNOUNCEMENT_MESSAGE)
    except Exception as e:
        print(f"Deploy announcement tracking failed: {e}")
        return

    if not should_announce:
        return

    try:
        await announce_channel.send(DEPLOY_ANNOUNCEMENT_MESSAGE)
    except Exception as e:
        print(f"Error sending deploy announcement: {e}")

@bot.event
async def on_ready():
    print(f"✅ Bot is online: {bot.user}")
    print(
        f"Tracking #{TARGET_CHANNEL_NAME}, reporting to #{REPORT_CHANNEL_NAME}, "
        f"vocab in #{VOCAB_CHANNEL_NAME}, news in #{NEWS_CHANNEL_NAME}, "
        f"app timezone: {APP_TIMEZONE_NAME}."
    )
    db.init_db()
    await send_deploy_announcement_once()
    if not clock_task.is_running():
        clock_task.start()


# ────────────────────────────────────────────
# MASTER CLOCK
# ────────────────────────────────────────────

@tasks.loop(minutes=1)
async def clock_task():
    global last_auto_report_date

    now = datetime.now(timezone.utc)
    h, m = now.hour, now.minute

    if h in SEND_HOURS_UTC and m == 0:
        await send_word_batch(bot, client_ai, VOCAB_CHANNEL_NAME)

    if h == NEWS_SEND_HOUR_UTC and m == 0:
        await send_daily_news(bot, client_ai, NEWS_CHANNEL_NAME)

    if h == REPORT_HOUR_UTC and m == 0:
        report_date = today_local()
        if last_auto_report_date != report_date:
            report_end_utc = now.replace(minute=0, second=0, microsecond=0)
            await send_daily_report(report_date=report_date, report_end_utc=report_end_utc)
            last_auto_report_date = report_date


def log_unchecked_message(discord_id, username, channel_id, text, reason):
    try:
        db.log_message(
            discord_id=discord_id,
            username=username,
            channel_id=channel_id,
            original_text=text,
            corrected_text="",
            natural_rewrite="",
            has_error=None,
            error_types=[reason],
            formality_score=None,
        )
    except Exception as e:
        print(f"Database error while logging unchecked message: {e}")


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
    discord_id = str(message.author.id)
    username = message.author.display_name
    channel_id = str(message.channel.id)

    if not text:
        await bot.process_commands(message)
        return

    if text.startswith(bot.command_prefix):
        await bot.process_commands(message)
        return

    if len(text) < MIN_LENGTH:
        log_unchecked_message(discord_id, username, channel_id, text, "too_short_to_check")
        await bot.process_commands(message)
        return

    try:
        result = check_grammar(client_ai, text)
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        log_unchecked_message(discord_id, username, channel_id, text, "grammar_check_failed")
        await bot.process_commands(message)
        return

    if result is None:
        log_unchecked_message(discord_id, username, channel_id, text, "grammar_check_parse_failed")
        await bot.process_commands(message)
        return

    has_error = bool(result.get("has_error"))
    new_vocab = result.get("new_vocab") or []
    formality_score = result.get("formality_score")

    try:
        db.log_message(
            discord_id=discord_id,
            username=username,
            channel_id=channel_id,
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
            stat_date=today_local(),
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

ERROR_META = {
    "tense": {
        "label": "Wrong verb tense",
        "tip": "Review simple past vs present perfect, and make sure your tense stays consistent within a sentence.",
    },
    "subject_verb_agreement": {
        "label": "Subject-verb agreement",
        "tip": "Remember: singular subjects take singular verbs (he *goes*, not *go*). Watch out for tricky subjects like 'everyone' or 'the team'.",
    },
    "preposition": {
        "label": "Wrong preposition",
        "tip": "Prepositions are tricky — try to memorize common combos (interested *in*, good *at*, depend *on*) rather than translating from Vietnamese.",
    },
    "article": {
        "label": "Missing or wrong article",
        "tip": "Use 'a/an' for something mentioned for the first time or non-specific, and 'the' for something specific or already known.",
    },
    "word_order": {
        "label": "Wrong word order",
        "tip": "English is Subject-Verb-Object. Adverbs usually go after the verb or at the end, not between the subject and verb.",
    },
    "spelling": {
        "label": "Spelling mistake",
        "tip": "Turn on autocorrect or spellcheck in your keyboard. For recurring words, try writing them out 3-5 times to build muscle memory.",
    },
    "word_choice": {
        "label": "Wrong word choice",
        "tip": "When in doubt, look up the word in context (not just the translation). Collocations matter — it's 'make a mistake', not 'do a mistake'.",
    },
    "other": {
        "label": "Other grammar issue",
        "tip": "Keep chatting and pay attention to the corrections — patterns will become clearer over time.",
    },
}


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


def build_error_analysis(error_counts):
    if not error_counts:
        return "  🎉 No grammar errors in this report window — great job!\n"

    sorted_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    lines = ["  🔍 **Main errors in this report window:**"]
    for error_type, count in sorted_errors:
        meta = ERROR_META.get(error_type, ERROR_META["other"])
        lines.append(f"    • **{meta['label']}** ({count}x) — _{meta['tip']}_")
    return "\n".join(lines) + "\n"


async def send_report_block(channel, content):
    if len(content) <= DISCORD_MESSAGE_LIMIT:
        await channel.send(content)
        return

    chunks = []
    current = ""
    for line in content.splitlines(keepends=True):
        if len(current) + len(line) > DISCORD_MESSAGE_LIMIT:
            if current:
                chunks.append(current)
                current = ""
            while len(line) > DISCORD_MESSAGE_LIMIT:
                chunks.append(line[:DISCORD_MESSAGE_LIMIT])
                line = line[DISCORD_MESSAGE_LIMIT:]
        current += line
    if current:
        chunks.append(current)

    for chunk in chunks:
        await channel.send(chunk)


async def send_daily_report(report_date=None, report_end_utc=None):
    report_channel = discord.utils.get(
        [ch for guild in bot.guilds for ch in guild.text_channels],
        name=REPORT_CHANNEL_NAME,
    )
    if report_channel is None:
        print(f"⚠️ Report channel '#{REPORT_CHANNEL_NAME}' not found.")
        return

    start_utc, end_utc = report_window_bounds_utc(report_end_utc)
    report_date = report_date or local_date_for(end_utc)
    stats = db.get_activity_stats_between(
        as_db_utc_naive(start_utc),
        as_db_utc_naive(end_utc),
    )

    # Fallback for old deployments where messages_log may not have enough data.
    if not stats:
        stats = db.get_daily_stats(report_date)

    if not stats:
        await report_channel.send(
            f"📊 **Daily Report — {report_date.isoformat()}**\n"
            f"No tracked activity in #{TARGET_CHANNEL_NAME} for this report window. Let's chat more tomorrow! 💬"
        )
        return

    await send_report_block(report_channel, f"📊 **Daily Report — {report_date.isoformat()}**")

    for row in stats:
        username = row["username"]
        total = row["total_messages"] or 0
        correct = row["messages_correct"] or 0
        errors = row["messages_with_errors"] or 0
        unchecked = max(total - correct - errors, 0)
        vocab = row["new_vocab_count"] or 0
        avg_formality = row.get("avg_formality_score")
        try:
            error_counts = db.get_error_summary_between(
                row["discord_id"],
                as_db_utc_naive(start_utc),
                as_db_utc_naive(end_utc),
            )
        except Exception as e:
            print(f"Error fetching error summary for {username}: {e}")
            error_counts = {}

        user_lines = [
            f"**{username}**\n"
            f"  💬 Total tracked messages: **{total}**\n"
            f"  ✅ Correct sentences: **{correct}**\n"
            f"  ✏️ Incorrect sentences: **{errors}**\n"
        ]
        if unchecked:
            user_lines.append(f"  ⚪ Unchecked messages: **{unchecked}**\n")
        user_lines.extend([
            f"  📖 New vocab spotted: **{vocab}** word(s)\n",
            f"  🎭 Writing style: **{formality_label(avg_formality)}**\n",
            build_error_analysis(error_counts),
        ])
        await send_report_block(report_channel, "".join(user_lines))

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
    try:
        await ctx.send("Generating report...")
        await send_daily_report()
        await ctx.send("Report sent! ✅")
    except Exception as e:
        print(f"!report command failed: {e}")
        await ctx.send(f"Report failed: `{type(e).__name__}`. Check bot logs for details.")


@bot.command(name="vocab")
async def vocab_cmd(ctx):
    """Manually trigger the next vocab drop (for testing)."""
    await send_word_batch(bot, client_ai, VOCAB_CHANNEL_NAME)
    await ctx.send("Vocab drop sent! 📚")


@bot.command(name="news")
async def news_cmd(ctx):
    """Manually trigger today's daily news drop."""
    await ctx.send("Fetching today's articles... 📰")
    await send_daily_news(bot, client_ai, NEWS_CHANNEL_NAME)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"Command '{ctx.command}' failed: {error}")
    await ctx.send(f"Command failed: `{type(error).__name__}`.")


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

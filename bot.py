import json
import logging
import os
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from openai import AsyncOpenAI


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("english-buddy")


def required_env(name: str) -> str:
    """Read a required environment variable without ever logging its value."""
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


DISCORD_BOT_TOKEN = required_env("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = required_env("OPENAI_API_KEY")
TARGET_CHANNEL_NAME = os.getenv("TARGET_CHANNEL_NAME", "chat-en").strip() or "chat-en"
AUTO_CHECK_ENABLED = os.getenv("AUTO_CHECK_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
MIN_LENGTH = 6
MAX_INPUT_LENGTH = 2_000

client_ai = AsyncOpenAI(api_key=OPENAI_API_KEY, timeout=30.0, max_retries=2)

intents = discord.Intents.default()
# Reading arbitrary message content is a privileged Discord intent. Keep it off by
# default so the bot can always start; /check works without it.
intents.message_content = AUTO_CHECK_ENABLED


class EnglishBuddy(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=intents)
        self.guild_commands_synced = False

    async def setup_hook(self) -> None:
        synced = await self.tree.sync()
        logger.info("Synced %s global application command(s)", len(synced))


bot = EnglishBuddy()

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


def valid_result(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not isinstance(value.get("has_error"), bool):
        return None

    for field in ("corrected", "natural_rewrite", "explanation"):
        if not isinstance(value.get(field), str):
            return None

    return value


async def check_grammar(text: str) -> dict[str, Any] | None:
    response = await client_ai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text[:MAX_INPUT_LENGTH]},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    if not content:
        return None

    try:
        return valid_result(json.loads(content))
    except json.JSONDecodeError:
        return None


def correction_text(original: str, result: dict[str, Any]) -> str:
    original = discord.utils.escape_markdown(original)
    lines = [f"**Câu gốc:** {original}"]

    if result["corrected"]:
        lines.append(f"**Sửa lại:** {discord.utils.escape_markdown(result['corrected'])}")
    if result["natural_rewrite"] and result["natural_rewrite"] != result["corrected"]:
        lines.append(
            "**Cách nói tự nhiên hơn:** "
            f"{discord.utils.escape_markdown(result['natural_rewrite'])}"
        )
    if result["explanation"]:
        lines.append(
            f"**Giải thích:** {discord.utils.escape_markdown(result['explanation'])}"
        )

    return "\n".join(lines)[:2_000]


@bot.event
async def on_ready() -> None:
    mode = "automatic + /check" if AUTO_CHECK_ENABLED else "/check only"
    logger.info("Bot online as %s | mode=%s", bot.user, mode)

    # Guild sync makes new slash commands appear immediately instead of waiting
    # for Discord's global-command cache to refresh.
    if not bot.guild_commands_synced:
        for guild in bot.guilds:
            try:
                bot.tree.copy_global_to(guild=guild)
                synced = await bot.tree.sync(guild=guild)
                logger.info(
                    "Synced %s application command(s) to guild %s (%s)",
                    len(synced),
                    guild.name,
                    guild.id,
                )
            except discord.HTTPException:
                logger.exception("Could not sync commands to guild %s", guild.id)
        bot.guild_commands_synced = True


@bot.tree.command(name="check", description="Kiểm tra ngữ pháp một câu tiếng Anh")
@app_commands.describe(text="Câu tiếng Anh cần kiểm tra")
async def check_command(interaction: discord.Interaction, text: str) -> None:
    # A public response can be used as the starter message for a correction
    # thread. Ephemeral responses are visible only to the caller and cannot
    # create threads.
    await interaction.response.defer(thinking=True)

    clean_text = text.strip()
    if not clean_text:
        await interaction.edit_original_response(
            content="Vui lòng nhập một câu tiếng Anh."
        )
        return

    try:
        result = await check_grammar(clean_text)
    except Exception:
        logger.exception("OpenAI request failed for /check")
        await interaction.edit_original_response(
            content="Không thể kiểm tra lúc này. Vui lòng thử lại sau."
        )
        return

    if result is None:
        await interaction.edit_original_response(
            content="Không đọc được kết quả từ AI. Vui lòng thử lại."
        )
    elif not result["has_error"]:
        safe_text = discord.utils.escape_markdown(clean_text)
        await interaction.edit_original_response(
            content=f"✅ **Câu đúng và tự nhiên:** {safe_text}",
            allowed_mentions=discord.AllowedMentions.none(),
        )
    else:
        starter = await interaction.edit_original_response(
            content=(
                "✏️ **Câu cần chỉnh:** "
                f"{discord.utils.escape_markdown(clean_text)}"
            )[:2_000],
            allowed_mentions=discord.AllowedMentions.none(),
        )
        try:
            thread = await starter.create_thread(
                name=f"Sửa câu của {interaction.user.display_name}"[:100],
                auto_archive_duration=60,
            )
            await thread.send(
                correction_text(clean_text, result),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            logger.exception(
                "Could not create correction thread for interaction %s",
                interaction.id,
            )
            await interaction.edit_original_response(
                content=correction_text(clean_text, result),
                allowed_mentions=discord.AllowedMentions.none(),
            )


@bot.tree.command(name="strictness", description="Cấu hình độ khắt khe (sắp ra mắt)")
async def strictness_slash(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        "Tính năng này sẽ được thêm ở phiên bản sau! 🚧", ephemeral=True
    )


@bot.tree.command(name="help", description="Hiển thị hướng dẫn sử dụng bot")
async def help_slash(interaction: discord.Interaction) -> None:
    auto_status = "đang bật" if AUTO_CHECK_ENABLED else "đang tắt"
    await interaction.response.send_message(
        "**English Buddy**\n"
        "`/check text: ...` — kiểm tra một câu tiếng Anh\n"
        "`/strictness` — cấu hình độ khắt khe (sắp ra mắt)\n"
        f"Tự động kiểm tra trong `#{TARGET_CHANNEL_NAME}`: **{auto_status}**",
        ephemeral=True,
    )


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return
    if not AUTO_CHECK_ENABLED:
        await bot.process_commands(message)
        return
    if getattr(message.channel, "name", None) != TARGET_CHANNEL_NAME:
        await bot.process_commands(message)
        return

    text = message.content.strip()
    if len(text) < MIN_LENGTH:
        await bot.process_commands(message)
        return

    try:
        result = await check_grammar(text)
    except Exception:
        logger.exception("OpenAI request failed for message %s", message.id)
        await bot.process_commands(message)
        return

    if result is None:
        logger.warning("Invalid AI result for message %s", message.id)
        await bot.process_commands(message)
        return

    if not result["has_error"]:
        try:
            await message.add_reaction("✅")
        except discord.HTTPException:
            logger.exception("Could not add reaction to message %s", message.id)
        await bot.process_commands(message)
        return

    try:
        await message.add_reaction("✏️")
        thread = await message.create_thread(
            name=f"Sửa câu của {message.author.display_name}"[:100],
            auto_archive_duration=60,
        )
        await thread.send(
            correction_text(text, result),
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.HTTPException:
        logger.exception("Could not send correction for message %s", message.id)

    await bot.process_commands(message)


@bot.command(name="strictness")
async def strictness(ctx: commands.Context, level: str | None = None) -> None:
    """Placeholder retained from the original bot for Phase 2."""
    await ctx.send("Tính năng này sẽ được thêm ở phiên bản sau! 🚧")


if __name__ == "__main__":
    logger.info(
        "Starting English Buddy | auto_check=%s | target_channel=%s",
        AUTO_CHECK_ENABLED,
        TARGET_CHANNEL_NAME,
    )
    bot.run(DISCORD_BOT_TOKEN, log_handler=None)

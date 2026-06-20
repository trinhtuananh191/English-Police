import os
import json
import discord
from discord.ext import commands
from openai import OpenAI

# ====== CONFIG (lấy từ Environment Variables trên Railway) ======
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# Tên channel mà bot sẽ tự động check ngữ pháp. Đổi tên này nếu channel của bạn tên khác.
TARGET_CHANNEL_NAME = os.getenv("TARGET_CHANNEL_NAME", "chat-en")
# Số ký tự tối thiểu để bot check (tránh check mấy câu kiểu "ok", "lol")
MIN_LENGTH = 6

# ====== DEBUG: kiểm tra xem Railway có truyền đúng biến môi trường vào không ======
print("---- DEBUG ENV CHECK ----")
print(f"DISCORD_BOT_TOKEN tồn tại: {bool(DISCORD_BOT_TOKEN)}, độ dài: {len(DISCORD_BOT_TOKEN) if DISCORD_BOT_TOKEN else 0}")
print(f"DISCORD_BOT_TOKEN bắt đầu bằng: {DISCORD_BOT_TOKEN[:7] if DISCORD_BOT_TOKEN else 'KHÔNG CÓ GIÁ TRỊ'}")
print(f"DISCORD_BOT_TOKEN kết thúc bằng: {DISCORD_BOT_TOKEN[-5:] if DISCORD_BOT_TOKEN else 'KHÔNG CÓ GIÁ TRỊ'}")
print(f"DISCORD_BOT_TOKEN có khoảng trắng/xuống dòng thừa: {DISCORD_BOT_TOKEN != DISCORD_BOT_TOKEN.strip() if DISCORD_BOT_TOKEN else 'N/A'}")
print(f"DISCORD_BOT_TOKEN có đủ 2 dấu chấm (định dạng JWT-like hợp lệ): {DISCORD_BOT_TOKEN.count('.') == 2 if DISCORD_BOT_TOKEN else 'N/A'}")
print("")
print(f"OPENAI_API_KEY tồn tại: {bool(OPENAI_API_KEY)}, độ dài: {len(OPENAI_API_KEY) if OPENAI_API_KEY else 0}")
print(f"OPENAI_API_KEY bắt đầu bằng: {OPENAI_API_KEY[:7] if OPENAI_API_KEY else 'KHÔNG CÓ GIÁ TRỊ'}")
print(f"OPENAI_API_KEY có khoảng trắng/xuống dòng thừa: {OPENAI_API_KEY != OPENAI_API_KEY.strip() if OPENAI_API_KEY else 'N/A'}")
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
    """Gọi OpenAI API để check grammar, trả về dict kết quả."""
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
    print(f"✅ Bot đã online: {bot.user}")


@bot.event
async def on_message(message: discord.Message):
    # Bỏ qua tin nhắn của chính bot
    if message.author.bot:
        return

    # Chỉ xử lý trong đúng channel mục tiêu
    if message.channel.name != TARGET_CHANNEL_NAME:
        await bot.process_commands(message)
        return

    text = message.content.strip()

    # Bỏ qua tin nhắn quá ngắn hoặc chỉ có link/emoji
    if len(text) < MIN_LENGTH:
        await bot.process_commands(message)
        return

    try:
        result = await check_grammar(text)
    except Exception as e:
        print(f"Lỗi khi gọi OpenAI API: {e}")
        await bot.process_commands(message)
        return

    if result is None:
        await bot.process_commands(message)
        return

    if not result.get("has_error"):
        # Câu đúng -> react dấu tick cho gọn, không spam chat
        try:
            await message.add_reaction("✅")
        except Exception:
            pass
    else:
        # Câu có lỗi -> tạo thread riêng để không làm loãng channel chính
        try:
            await message.add_reaction("✏️")
            thread = await message.create_thread(
                name=f"Sửa câu của {message.author.display_name}",
                auto_archive_duration=60,
            )
            reply_lines = [f"**Câu gốc:** {text}"]
            if result.get("corrected"):
                reply_lines.append(f"**Sửa lại:** {result['corrected']}")
            if result.get("natural_rewrite") and result["natural_rewrite"] != result.get("corrected"):
                reply_lines.append(f"**Cách nói tự nhiên hơn:** {result['natural_rewrite']}")
            if result.get("explanation"):
                reply_lines.append(f"**Giải thích:** {result['explanation']}")

            await thread.send("\n".join(reply_lines))
        except Exception as e:
            print(f"Lỗi khi gửi correction: {e}")

    await bot.process_commands(message)


@bot.command(name="strictness")
async def strictness(ctx, level: str = None):
    """Lệnh tạm thời - placeholder cho tính năng config độ khắt khe (Phase 2)."""
    await ctx.send("Tính năng này sẽ được thêm ở phiên bản sau! 🚧")


if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        raise ValueError("Thiếu DISCORD_BOT_TOKEN trong Environment Variables!")
    if not OPENAI_API_KEY:
        raise ValueError("Thiếu OPENAI_API_KEY trong Environment Variables!")
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except discord.errors.LoginFailure as e:
        print(f"❌ LỖI LOGIN DISCORD: Token không hợp lệ. Chi tiết: {e}")
    except Exception as e:
        print(f"❌ LỖI KHÔNG XÁC ĐỊNH khi chạy bot: {e}")


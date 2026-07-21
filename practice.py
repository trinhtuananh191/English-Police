"""Vietnamese-to-English translation practice powered by OpenAI.

The module owns challenge generation, detailed grading, Discord formatting, and
the twice-daily shared practice drop. Per-user progress and shared prompt IDs are
persisted by :mod:`database` so practice can continue after a bot restart.
"""

import asyncio
import json
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from openai import OpenAI
else:
    OpenAI = Any

from time_utils import now_local


PRACTICE_MODEL = os.getenv("PRACTICE_MODEL", "gpt-4o-mini")
DISCORD_MESSAGE_LIMIT = 2000


def _parse_send_hours(value: str) -> tuple[int, ...]:
    try:
        hours = tuple(sorted({int(item.strip()) for item in value.split(",") if item.strip()}))
        if not hours or any(hour < 0 or hour > 23 for hour in hours):
            raise ValueError
        return hours
    except (TypeError, ValueError):
        print(f"Invalid PRACTICE_SEND_HOURS_LOCAL '{value}', falling back to 9,14,21.")
        return (9, 14, 21)


PRACTICE_SEND_HOURS_LOCAL = _parse_send_hours(
    os.getenv("PRACTICE_SEND_HOURS_LOCAL", "9,14,21")
)


def _database():
    """Import the deployment-only PostgreSQL dependency when scheduling needs it."""
    import database

    return database


COUNTRY_FLAGS = {
    "British English": "🇬🇧",
    "American English": "🇺🇸",
    "Australian English": "🇦🇺",
    "Canadian English": "🇨🇦",
}

TOPIC_ROTATION = [
    "Cuộc sống hằng ngày",
    "Công việc",
    "Bạn bè",
    "Mối quan hệ",
    "Sở thích",
    "Du lịch",
    "Sức khỏe",
    "Công nghệ",
    "Quan điểm cá nhân",
    "Kể lại trải nghiệm",
    "Workplace conversation",
    "Formal communication",
]

VARIANT_ROTATION = [
    "British English",
    "American English",
    "Australian English",
    "Canadian English",
]

CHALLENGE_SYSTEM_PROMPT = """You are an experienced native English teacher for Vietnamese learners.
Create one Vietnamese-to-English translation exercise. The learner must receive only the Vietnamese prompt, never an English answer.

Requirements:
- Make it practical and natural for real conversation or communication.
- Explicitly identify the English country variant, level/context label, and concrete conversation context.
- Avoid translationese and design the exercise to teach natural collocations or sentence patterns.
- Keep the Vietnamese prompt to one sentence or a short two-sentence paragraph.
- Increase difficulty gradually when learner history shows strong performance.

Return ONLY one JSON object with this schema:
{
  "variant": "British English",
  "level": "Casual / Everyday life",
  "context": "Mô tả ngắn bằng tiếng Việt",
  "vietnamese_prompt": "Câu tiếng Việt cần dịch"
}
"""

REVIEW_SYSTEM_PROMPT = """Bạn là giáo viên tiếng Anh bản ngữ giàu kinh nghiệm dạy người Việt. Bạn chấm bài dịch từ tiếng Việt sang tiếng Anh, mô phỏng cách nói tự nhiên tại Anh, Mỹ, Úc hoặc Canada theo đúng biến thể đã ghi trong bài.

MỤC TIÊU
- Đánh giá đúng ngữ pháp, từ vựng, naturalness, collocation và cách diễn đạt native-like.
- Phân biệt rõ "sai ngữ pháp" với "đúng nhưng chưa tự nhiên".
- Chỉ ra lối dịch word-by-word và giúp người học tư duy trực tiếp bằng tiếng Anh.
- Luôn giải thích bằng tiếng Việt. Ví dụ tiếng Anh phải có nghĩa tiếng Việt khi hữu ích.

FEEDBACK_MARKDOWN bắt buộc có các phần sau, theo đúng thứ tự:
1. "## Câu của tôi": trích nguyên văn câu người học.
2. "# Điểm: X/10" và điểm riêng Grammar, Vocabulary, Naturalness, Native-like expression.
3. "## Nhận xét chung": mức độ truyền tải ý, điểm làm tốt và lỗi chính.
4. "# Phân tích từng lỗi": tách từng lỗi, đánh số, trích phần sai và đưa cách đúng/tự nhiên hơn. Giải thích vì sao chưa tự nhiên trong context.
5. Nếu dùng sai một từ, bắt buộc ghi cả "Từ tôi dùng" và "Từ đúng", mỗi từ gồm từ loại, IPA, nghĩa tiếng Việt; so sánh các từ dễ nhầm, cho ví dụ và thêm "Cách nhớ" khi có thể.
6. "# Các cụm từ hoặc cấu trúc đáng học": ghi cụm, nghĩa tiếng Việt, ví dụ tiếng Anh và bản dịch. Ưu tiên collocation/phrasal verb/pattern tái sử dụng được.
7. "# Giải thích ngữ pháp" nếu có lỗi ngữ pháp: giải thích lý do, dấu hiệu, khi nào dùng, pattern/công thức và 2-3 ví dụ thực tế. Nếu không có lỗi ngữ pháp, nói ngắn gọn rằng không cần sửa ngữ pháp.
8. "# Phân biệt đúng ngữ pháp và tự nhiên": nói rõ phần nào không sai nhưng người bản ngữ ít dùng, nếu có.
9. "# Bản sửa tối thiểu": giữ gần nhất ý, cấu trúc và từ vựng của người học.
10. "# Phiên bản tự nhiên như người bản ngữ": dùng cờ quốc gia phù hợp và giải thích ngắn vì sao tự nhiên hơn.
11. "# Những cụm tôi nên lưu lại": chọn 3-6 cụm hữu ích, mỗi cụm có nghĩa, câu ví dụ và bản dịch.
12. "# Phiên bản casual/native nâng cao" nếu phù hợp; giải thích từ/cụm mới quan trọng, gồm từ loại và IPA khi là từ vựng mới.

Không được chép lại bài tiếp theo vào feedback_markdown. Bài tiếp theo nằm riêng trong next_challenge, phải luân phiên chủ đề và điều chỉnh độ khó dựa trên bài hiện tại cùng lịch sử gần đây. Không đưa đáp án tiếng Anh của bài tiếp theo.

Return ONLY one valid JSON object with this schema:
{
  "overall_score": 7.5,
  "grammar_score": 8,
  "vocabulary_score": 7,
  "naturalness_score": 7,
  "native_like_score": 6.5,
  "error_summary": "Tóm tắt ngắn các lỗi để điều chỉnh bài sau",
  "feedback_markdown": "Nội dung chấm chi tiết bằng Markdown",
  "next_challenge": {
    "variant": "American English",
    "level": "Workplace / Intermediate",
    "context": "Mô tả ngắn bằng tiếng Việt",
    "vietnamese_prompt": "Câu tiếng Việt mới cần dịch"
  }
}
"""


def _response_json(response) -> dict:
    content = response.choices[0].message.content.strip()
    if content.startswith("```"):
        parts = content.split("```")
        content = parts[1] if len(parts) > 1 else content
        if content.lstrip().startswith("json"):
            content = content.lstrip()[4:]
    payload = json.loads(content.strip())
    if not isinstance(payload, dict):
        raise ValueError("OpenAI response was not a JSON object")
    return payload


def _normalise_challenge(payload: dict, fallback_variant: str = "British English") -> dict:
    variant = str(payload.get("variant") or fallback_variant).strip()
    if variant not in COUNTRY_FLAGS:
        variant = fallback_variant

    challenge = {
        "variant": variant,
        "level": str(payload.get("level") or "Casual / Everyday life").strip(),
        "context": str(payload.get("context") or "Một tình huống giao tiếp hằng ngày").strip(),
        "vietnamese_prompt": str(
            payload.get("vietnamese_prompt") or payload.get("vietnamese_sentence") or ""
        ).strip(),
    }
    if not challenge["vietnamese_prompt"]:
        raise ValueError("OpenAI response did not include a Vietnamese practice prompt")
    return challenge


def _score(value) -> float:
    try:
        return max(0.0, min(10.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def generate_challenge(
    client_ai: OpenAI,
    round_number: int,
    recent_history: Optional[list] = None,
    variant_hint: Optional[str] = None,
    topic_hint: Optional[str] = None,
) -> dict:
    """Generate one translation prompt without revealing its English answer."""
    recent_history = recent_history or []
    if round_number <= 1 and not variant_hint:
        variant_hint = "British English"
    variant_hint = variant_hint or VARIANT_ROTATION[(round_number - 1) % len(VARIANT_ROTATION)]
    topic_hint = topic_hint or TOPIC_ROTATION[(round_number - 1) % len(TOPIC_ROTATION)]

    history_payload = [dict(row) for row in recent_history[:5]]
    user_prompt = (
        f"Create Round {round_number}.\n"
        f"Preferred variant: {variant_hint}\n"
        f"Topic to use next: {topic_hint}\n"
        f"Recent learner history (newest first): "
        f"{json.dumps(history_payload, ensure_ascii=False, default=str)}\n"
        "For a learner with no history, start at Casual / Everyday life. Return JSON only."
    )
    response = client_ai.chat.completions.create(
        model=PRACTICE_MODEL,
        messages=[
            {"role": "system", "content": CHALLENGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.8,
        max_tokens=500,
        response_format={"type": "json_object"},
    )
    return _normalise_challenge(_response_json(response), variant_hint)


def review_translation(
    client_ai: OpenAI,
    challenge: dict,
    learner_answer: str,
    round_number: int,
    recent_history: Optional[list] = None,
) -> dict:
    """Grade one answer and return structured feedback plus the next challenge."""
    recent_history = recent_history or []
    history_payload = [dict(row) for row in recent_history[:5]]
    user_payload = {
        "round_number": round_number,
        "challenge": challenge,
        "learner_answer_verbatim": learner_answer,
        "recent_history_newest_first": history_payload,
        "next_topic_hint": TOPIC_ROTATION[round_number % len(TOPIC_ROTATION)],
        "next_variant_hint": VARIANT_ROTATION[round_number % len(VARIANT_ROTATION)],
    }
    response = client_ai.chat.completions.create(
        model=PRACTICE_MODEL,
        messages=[
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Chấm bài theo dữ liệu JSON sau:\n"
                + json.dumps(user_payload, ensure_ascii=False, default=str),
            },
        ],
        temperature=0.35,
        max_tokens=4000,
        response_format={"type": "json_object"},
    )
    payload = _response_json(response)
    feedback = str(payload.get("feedback_markdown") or "").strip()
    if not feedback:
        raise ValueError("OpenAI response did not include practice feedback")

    return {
        "overall_score": _score(payload.get("overall_score")),
        "grammar_score": _score(payload.get("grammar_score")),
        "vocabulary_score": _score(payload.get("vocabulary_score")),
        "naturalness_score": _score(payload.get("naturalness_score")),
        "native_like_score": _score(payload.get("native_like_score")),
        "error_summary": str(payload.get("error_summary") or "").strip(),
        "feedback_markdown": feedback,
        "next_challenge": _normalise_challenge(
            payload.get("next_challenge") or {},
            VARIANT_ROTATION[round_number % len(VARIANT_ROTATION)],
        ),
    }


def format_challenge(
    challenge: dict,
    round_number: Optional[int] = None,
    daily: bool = False,
) -> str:
    """Format a challenge without exposing an English model answer."""
    variant = challenge["variant"]
    flag = COUNTRY_FLAGS.get(variant, "🌍")
    title = "Daily Practice" if daily else f"Round {round_number or 1}"
    instructions = "Gửi bản dịch tiếng Anh của bạn trong thread này."
    return (
        f"### {title} - {flag} {variant}\n\n"
        f"**Level:** {challenge['level']}\n"
        f"**Context:** {challenge['context']}\n\n"
        f"{challenge['vietnamese_prompt']}\n\n"
        f"_{instructions} Bot sẽ chấm chi tiết và đưa bài tiếp theo._"
    )


def format_review_with_next(result: dict, next_round_number: int) -> str:
    return (
        f"{result['feedback_markdown'].rstrip()}\n\n"
        f"---\n\n"
        f"{format_challenge(result['next_challenge'], next_round_number)}"
    )


def split_discord_message(content: str, limit: int = DISCORD_MESSAGE_LIMIT) -> list[str]:
    """Split long tutor feedback at readable boundaries for Discord."""
    remaining = content.strip()
    chunks = []
    while len(remaining) > limit:
        boundary = remaining.rfind("\n\n", 0, limit + 1)
        if boundary < limit // 2:
            boundary = remaining.rfind("\n", 0, limit + 1)
        if boundary < limit // 2:
            boundary = remaining.rfind(" ", 0, limit + 1)
        if boundary <= 0:
            boundary = limit
        chunks.append(remaining[:boundary].rstrip())
        remaining = remaining[boundary:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


async def send_long_message(channel, content: str, reply_to=None):
    """Send all chunks, replying to the learner with the first one when possible."""
    chunks = split_discord_message(content)
    for index, chunk in enumerate(chunks):
        if index == 0 and reply_to is not None:
            await reply_to.reply(chunk, mention_author=False)
        else:
            await channel.send(chunk)


async def create_practice_thread(starter_message, name: str, participant=None):
    """Create a public practice thread and add its intended participant when possible."""
    thread = await starter_message.create_thread(
        name=name[:100],
        auto_archive_duration=1440,
        reason="English translation practice",
    )
    if participant is not None:
        try:
            await thread.add_user(participant)
        except Exception as exc:
            print(f"Could not add practice participant to thread: {exc}")
    return thread


def _daily_hints(local_now: datetime) -> tuple[str, str]:
    slot_index = PRACTICE_SEND_HOURS_LOCAL.index(local_now.hour)
    rotation_index = local_now.date().toordinal() * len(PRACTICE_SEND_HOURS_LOCAL) + slot_index
    topic = TOPIC_ROTATION[rotation_index % len(TOPIC_ROTATION)]
    variant = VARIANT_ROTATION[rotation_index % len(VARIANT_ROTATION)]
    return variant, topic


async def send_scheduled_practice(bot, client_ai: OpenAI, channel_name: str, local_now=None) -> bool:
    """Post one durable shared challenge at each configured local send hour."""
    local_now = local_now or now_local()
    if local_now.hour not in PRACTICE_SEND_HOURS_LOCAL or local_now.minute != 0:
        return False

    schedule_key = f"{local_now.date().isoformat()}:{local_now.hour:02d}"
    database = _database()
    try:
        if database.scheduled_practice_exists(schedule_key):
            return False
    except Exception as exc:
        print(f"Could not check scheduled practice key '{schedule_key}': {exc}")
        return False

    practice_channel = next(
        (
            channel
            for guild in bot.guilds
            for channel in guild.text_channels
            if channel.name == channel_name
        ),
        None,
    )
    if practice_channel is None:
        print(f"⚠️ Practice channel '#{channel_name}' not found.")
        return False

    variant_hint, topic_hint = _daily_hints(local_now)
    challenge = await asyncio.to_thread(
        generate_challenge,
        client_ai,
        round_number=1,
        variant_hint=variant_hint,
        topic_hint=topic_hint,
    )
    starter = await practice_channel.send(
        f"@everyone 🧵 **Daily Practice {local_now.strftime('%d/%m - %H:%M')}** — "
        "mở thread để làm bài."
    )
    thread = await create_practice_thread(
        starter,
        name=f"Daily Practice - {local_now.strftime('%d-%m %Hh')}",
    )
    message = await thread.send(format_challenge(challenge, daily=True))
    try:
        await message.add_reaction("✍️")
    except Exception:
        pass

    database.save_scheduled_practice(
        schedule_key=schedule_key,
        prompt_message_id=str(message.id),
        channel_id=str(thread.id),
        variant=challenge["variant"],
        level=challenge["level"],
        context=challenge["context"],
        vietnamese_prompt=challenge["vietnamese_prompt"],
    )
    return True

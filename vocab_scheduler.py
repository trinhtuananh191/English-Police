"""
Vocab Drop scheduler module.
- AI generates 10 brand-new words per day across all categories.
- Words already used (stored in DB) are never repeated.
- Posts 5 words × 2 times per day: 12:00 and 20:00 ICT (05:00 and 13:00 UTC).
- Each word gets a fresh AI-generated casual example sentence.
"""

import json
from datetime import date, datetime, timezone
from openai import OpenAI
import database as db

# UTC hours for each batch  (ICT = UTC+7)
# 05:00 UTC = 12:00 ICT
# 13:00 UTC = 20:00 ICT
SEND_HOURS_UTC = [5, 13]
WORDS_PER_BATCH = 5
WORDS_PER_DAY = 10

CATEGORIES = [
    "Slang / Gen-Z",
    "Daily Life",
    "Emotions / Feelings",
    "Relationships",
    "Work / Productivity",
    "Office / Corporate",
    "School / Study",
    "Tech",
    "Software Development",
    "Gaming",
    "Design / UI-UX",
    "Entertainment / Pop Culture",
    "Farm / Nature / Outdoors",
]

TOPIC_EMOJI = {
    "Slang / Gen-Z": "🤙",
    "Daily Life": "☀️",
    "Emotions / Feelings": "💭",
    "Relationships": "🫂",
    "Work / Productivity": "💼",
    "Office / Corporate": "🏢",
    "School / Study": "📚",
    "Tech": "💻",
    "Software Development": "🛠️",
    "Gaming": "🎮",
    "Design / UI-UX": "🎨",
    "Entertainment / Pop Culture": "🎬",
    "Farm / Nature / Outdoors": "🌿",
}

GENERATE_VOCAB_PROMPT = """You are an English vocabulary curator for young Vietnamese adults (20-28 years old) learning English through casual daily chat. Your job is to generate exactly {count} English words or phrases that:
- Are genuinely useful and naturally used by native English speakers today
- Span a variety of difficulty (mix of intermediate and advanced)
- Are interesting, practical, and worth remembering
- Cover the topic/category: {category}

STRICT RULES:
- Never repeat any word from this already-used list: {used_words}
- Each entry must be unique
- Prefer collocations, phrasal verbs, idioms, and expressions over single basic words
- Casual/slang is totally fine for relevant categories

Respond ONLY with a valid JSON array, no extra text, no markdown:
[
  {{"word": "the word or phrase", "word_type": "noun/verb/expression/etc", "meaning": "clear short meaning in English", "topic": "{category}"}},
  ...
]
Return exactly {count} items."""

EXAMPLE_PROMPT = """Write ONE short casual example sentence (max 12 words) for the English word/phrase below. Make it sound like something a young person would actually text, not a textbook. Informal is fine.

Word: {word}
Type: {word_type}
Meaning: {meaning}

Respond with ONLY the sentence, nothing else."""


def generate_todays_words(client_ai: OpenAI) -> list:
    """
    Generate today's 10 words using AI, ensuring no repeats from DB history.
    Returns list of dicts: [{word, word_type, meaning, topic}, ...]
    """
    today = date.today()

    # Return cached words if already generated today (e.g. after a restart)
    cached = db.get_todays_generated_vocab(today)
    if len(cached) >= WORDS_PER_DAY:
        print(f"✅ Using {len(cached)} cached vocab words for today.")
        return [dict(row) for row in cached]

    used_words = db.get_all_used_words()
    used_sample = list(used_words)[:300]  # Cap to avoid token overflow

    import random
    random.shuffle(CATEGORIES)
    selected_categories = CATEGORIES[:WORDS_PER_DAY]  # 1 word per category, 10 categories

    all_words = []
    for category in selected_categories:
        used_str = ", ".join(f'"{w}"' for w in used_sample) if used_sample else "none yet"
        prompt = GENERATE_VOCAB_PROMPT.format(
            count=1,
            category=category,
            used_words=used_str,
        )
        try:
            response = client_ai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.9,
                max_tokens=200,
            )
            content = response.choices[0].message.content.strip()
            # Strip markdown fences if present
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            parsed = json.loads(content)
            if isinstance(parsed, list) and parsed:
                word_entry = parsed[0]
                word_entry["topic"] = category
                all_words.append(word_entry)
                used_sample.append(word_entry["word"].lower())
        except Exception as e:
            print(f"Error generating word for category '{category}': {e}")

    if all_words:
        db.save_generated_vocab_batch(all_words, today)
        print(f"✅ Generated and saved {len(all_words)} new vocab words for today.")

    return all_words


def generate_example(client_ai: OpenAI, word: str, word_type: str, meaning: str) -> str:
    """Generate a fresh casual example sentence for a word."""
    try:
        prompt = EXAMPLE_PROMPT.format(word=word, word_type=word_type, meaning=meaning)
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
            max_tokens=60,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating example for '{word}': {e}")
        return "example unavailable"


def format_word_card(word_entry: dict, example: str, index: int, total: int) -> str:
    topic = word_entry.get("topic", "")
    emoji = TOPIC_EMOJI.get(topic, "📖")
    topic_label = topic.upper()
    return (
        f"{emoji} **Word {index}/{total} — {topic_label}**\n"
        f"**{word_entry['word'].upper()}** _{word_entry.get('word_type', '')}_ \n"
        f"📌 {word_entry.get('meaning', '')}\n"
        f"💬 _{example}_\n"
        f"─────────────────\n"
        f"React 👍 if you knew this · 📝 if you're saving it!"
    )


async def send_word_batch(bot, client_ai: OpenAI, channel_name: str):
    """Post the correct 5-word batch for the current UTC hour."""
    import discord

    now_utc = datetime.now(timezone.utc)
    utc_hour = now_utc.hour

    if utc_hour not in SEND_HOURS_UTC:
        return

    vocab_channel = discord.utils.get(
        [ch for guild in bot.guilds for ch in guild.text_channels],
        name=channel_name,
    )
    if vocab_channel is None:
        print(f"⚠️ Vocab channel '#{channel_name}' not found.")
        return

    all_words = generate_todays_words(client_ai)
    if not all_words:
        await vocab_channel.send("⚠️ Could not generate vocab words today. Will retry next batch.")
        return

    batch_index = SEND_HOURS_UTC.index(utc_hour)
    start = batch_index * WORDS_PER_BATCH
    batch = all_words[start:start + WORDS_PER_BATCH]

    if not batch:
        return

    batch_num = batch_index + 1
    total_batches = len(SEND_HOURS_UTC)
    ict_labels = ["12:00 PM", "8:00 PM"]
    ict_label = ict_labels[batch_index]

    header = (
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📚 **VOCAB DROP** — {ict_label} · Batch {batch_num}/{total_batches}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await vocab_channel.send(header)

    for i, word_entry in enumerate(batch, start=1):
        global_index = start + i
        example = generate_example(
            client_ai,
            word_entry["word"],
            word_entry.get("word_type", ""),
            word_entry.get("meaning", ""),
        )
        card = format_word_card(word_entry, example, global_index, WORDS_PER_DAY)
        msg = await vocab_channel.send(card)
        try:
            await msg.add_reaction("👍")
            await msg.add_reaction("📝")
        except Exception:
            pass

"""
Daily News scheduler module.
- Fetches developer/design-focused articles from GNews once per day.
- Summarizes GNews descriptions with OpenAI.
- Posts the morning briefing to a configured Discord channel.
"""

import json
import html
import os
import random
import re
import urllib.error
import urllib.parse
import urllib.request

import discord
from openai import OpenAI

from time_utils import today_local

# 02:00 UTC = 09:00 ICT
NEWS_SEND_HOUR_UTC = 2
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")
GNEWS_SEARCH_URL = "https://gnews.io/api/v4/search"
GNEWS_TIMEOUT_SECONDS = 10
GNEWS_ARTICLES_PER_TOPIC = 2
GNEWS_RESULTS_PER_TOPIC = 10
USER_AGENT = "Mozilla/5.0 (compatible; EnglishBuddyBot/1.0)"

NEWS_TOPICS = [
    ("Tech 💻", "technology OR startup OR gadgets"),
    ("AI / ML 🤖", "artificial intelligence OR machine learning OR AI"),
    ("Design 🎨", "design OR UX OR UI"),
    ("Dev 🛠️", "programming OR software development OR GitHub"),
]

SUMMARY_PROMPT = """You are summarizing a tech/design article for a group of young Vietnamese developers and designers learning English. Write a SHORT, engaging summary in plain English (2-3 sentences max). Keep it casual but informative — highlight what's interesting or why it matters. No intro like "This article..." — just dive in.

Title: {title}
Excerpt: {excerpt}

Write the summary only, nothing else."""


def _strip_html(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:600]


def _article_from_gnews(item: dict, category: str):
    title = (item.get("title") or "").strip()
    link = (item.get("url") or "").strip()
    description = _strip_html(item.get("description") or item.get("content") or "")

    if not title or not link:
        return None

    return {
        "title": title,
        "link": link,
        "description": description,
        "category": category,
        "published_at": item.get("publishedAt") or "",
        "source": (item.get("source") or {}).get("name", ""),
    }


def _build_gnews_url(query: str, max_results: int) -> str:
    params = {
        "q": query,
        "lang": "en",
        "max": max_results,
        "in": "title,description",
        "sortby": "publishedAt",
        "apikey": GNEWS_API_KEY,
    }
    return f"{GNEWS_SEARCH_URL}?{urllib.parse.urlencode(params)}"


def fetch_gnews_articles(category: str, query: str, max_results: int = GNEWS_RESULTS_PER_TOPIC) -> list:
    """Fetch GNews search results for a topic. Returns an empty list on failure."""
    if not GNEWS_API_KEY:
        print("⚠️ Missing GNEWS_API_KEY in Environment Variables!")
        return []

    try:
        request = urllib.request.Request(
            _build_gnews_url(query, max_results),
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(request, timeout=GNEWS_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            pass
        print(f"GNews fetch error for '{category}' ({e.code}): {error_body or e.reason}")
        return []
    except Exception as e:
        print(f"GNews fetch error for '{category}': {e}")
        return []

    articles = []
    for item in payload.get("articles", []):
        article = _article_from_gnews(item, category)
        if article:
            articles.append(article)
    return articles


def collect_daily_articles() -> list:
    """Pick two recent articles from each configured GNews topic."""
    articles = []
    seen_links = set()

    for category, query in NEWS_TOPICS:
        topic_articles = fetch_gnews_articles(category, query)
        random.shuffle(topic_articles)

        selected_count = 0
        for article in topic_articles:
            if article["link"] in seen_links:
                continue
            articles.append(article)
            seen_links.add(article["link"])
            selected_count += 1
            if selected_count >= GNEWS_ARTICLES_PER_TOPIC:
                break

    return articles


def summarize_article(client_ai: OpenAI, article: dict) -> str:
    title = article.get("title", "")
    excerpt = article.get("description") or "No excerpt available."
    prompt = SUMMARY_PROMPT.format(title=title, excerpt=excerpt[:500])

    try:
        response = client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=120,
        )
        summary = response.choices[0].message.content.strip()
        return summary or "Summary unavailable."
    except Exception as e:
        print(f"Summary error for '{title}': {e}")
        return "Summary unavailable."


def format_article_card(article: dict, summary: str, index: int, category: str = "") -> str:
    return (
        f"**{index}. {article['title']}**\n"
        f"{summary}\n"
        f"🔗 {article['link']}"
    )


async def send_daily_news(bot, client_ai: OpenAI, channel_name: str):
    """Post the daily news briefing to the configured Discord channel."""
    news_channel = discord.utils.get(
        [ch for guild in bot.guilds for ch in guild.text_channels],
        name=channel_name,
    )
    if news_channel is None:
        print(f"⚠️ News channel '#{channel_name}' not found.")
        return

    articles = collect_daily_articles()
    if not articles:
        await news_channel.send("⚠️ Could not fetch any news articles today.")
        return

    today = today_local()
    header = (
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📰 **Daily News — {today.strftime('%B %d, %Y')}**\n"
        f"Your morning read: Tech · AI · Design · Dev\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await news_channel.send(header)

    posted_count = 0
    for article in articles:
        summary = summarize_article(client_ai, article)
        card = format_article_card(
            article,
            summary,
            posted_count + 1,
            article.get("category", ""),
        )

        try:
            msg = await news_channel.send(card)
            posted_count += 1
            try:
                await msg.add_reaction("🔖")
            except Exception:
                pass
        except Exception as e:
            print(f"Error posting article: {e}")

    await news_channel.send(
        f"─────────────────\n"
        f"That's your morning briefing! React 🔖 on anything you want to read later."
    )

"""
Database module — handles all PostgreSQL connections and queries.
Uses the DATABASE_URL environment variable that Railway automatically provides
when you attach a PostgreSQL database to your project.
"""

import os
import json
from datetime import date, datetime
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    """Create all tables if they don't exist yet. Safe to run every startup."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages_log (
            id SERIAL PRIMARY KEY,
            discord_id TEXT NOT NULL,
            username TEXT,
            channel_id TEXT,
            original_text TEXT,
            corrected_text TEXT,
            natural_rewrite TEXT,
            has_error BOOLEAN,
            error_types TEXT,
            formality_score REAL DEFAULT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS vocab_bank (
            id SERIAL PRIMARY KEY,
            discord_id TEXT NOT NULL,
            username TEXT,
            word_or_phrase TEXT,
            meaning TEXT,
            example_sentence TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            id SERIAL PRIMARY KEY,
            discord_id TEXT NOT NULL,
            username TEXT,
            stat_date DATE NOT NULL,
            total_messages INTEGER DEFAULT 0,
            messages_correct INTEGER DEFAULT 0,
            messages_with_errors INTEGER DEFAULT 0,
            new_vocab_count INTEGER DEFAULT 0,
            avg_formality_score REAL DEFAULT NULL,
            UNIQUE(discord_id, stat_date)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cefr_estimates (
            id SERIAL PRIMARY KEY,
            discord_id TEXT NOT NULL,
            username TEXT,
            estimated_level TEXT,
            estimated_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # Track all AI-generated vocab words so they are never repeated
    cur.execute("""
        CREATE TABLE IF NOT EXISTS generated_vocab (
            id SERIAL PRIMARY KEY,
            word TEXT NOT NULL UNIQUE,
            topic TEXT,
            word_type TEXT,
            meaning TEXT,
            generated_on DATE NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # Safe migrations for databases created by older bot versions.
    # CREATE TABLE IF NOT EXISTS does not add new columns to existing tables,
    # so keep these ALTER statements here to make Railway upgrades painless.
    cur.execute("""
        ALTER TABLE messages_log
        ADD COLUMN IF NOT EXISTS corrected_text TEXT,
        ADD COLUMN IF NOT EXISTS natural_rewrite TEXT,
        ADD COLUMN IF NOT EXISTS has_error BOOLEAN,
        ADD COLUMN IF NOT EXISTS error_types TEXT,
        ADD COLUMN IF NOT EXISTS formality_score REAL DEFAULT NULL;
    """)

    cur.execute("""
        ALTER TABLE daily_stats
        ADD COLUMN IF NOT EXISTS new_vocab_count INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS avg_formality_score REAL DEFAULT NULL;
    """)

    cur.execute("""
        ALTER TABLE generated_vocab
        ADD COLUMN IF NOT EXISTS topic TEXT,
        ADD COLUMN IF NOT EXISTS word_type TEXT,
        ADD COLUMN IF NOT EXISTS meaning TEXT,
        ADD COLUMN IF NOT EXISTS generated_on DATE,
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Database tables ready.")


def log_message(discord_id, username, channel_id, original_text, corrected_text,
                natural_rewrite, has_error, error_types, formality_score=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO messages_log
        (discord_id, username, channel_id, original_text, corrected_text,
         natural_rewrite, has_error, error_types, formality_score)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (discord_id, username, channel_id, original_text, corrected_text,
          natural_rewrite, has_error, json.dumps(error_types or []), formality_score))
    conn.commit()
    cur.close()
    conn.close()


def save_vocab(discord_id, username, word_or_phrase, meaning, example_sentence):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO vocab_bank (discord_id, username, word_or_phrase, meaning, example_sentence)
        VALUES (%s, %s, %s, %s, %s)
    """, (discord_id, username, word_or_phrase, meaning, example_sentence))
    conn.commit()
    cur.close()
    conn.close()


def upsert_daily_stat(discord_id, username, stat_date, has_error,
                      new_vocab_count=0, formality_score=None):
    """Increment today's stat row for a user (creates it if it doesn't exist)."""
    conn = get_connection()
    cur = conn.cursor()

    # Fetch existing avg to recalculate rolling average
    cur.execute("""
        SELECT total_messages, avg_formality_score FROM daily_stats
        WHERE discord_id = %s AND stat_date = %s
    """, (discord_id, stat_date))
    existing = cur.fetchone()

    if existing and formality_score is not None:
        n = existing["total_messages"]
        old_avg = existing["avg_formality_score"] or 0
        new_avg = ((old_avg * n) + formality_score) / (n + 1)
    elif formality_score is not None:
        new_avg = formality_score
    else:
        new_avg = None

    cur.execute("""
        INSERT INTO daily_stats (discord_id, username, stat_date, total_messages,
                                  messages_correct, messages_with_errors,
                                  new_vocab_count, avg_formality_score)
        VALUES (%s, %s, %s, 1, %s, %s, %s, %s)
        ON CONFLICT (discord_id, stat_date)
        DO UPDATE SET
            total_messages        = daily_stats.total_messages + 1,
            messages_correct      = daily_stats.messages_correct + %s,
            messages_with_errors  = daily_stats.messages_with_errors + %s,
            new_vocab_count       = daily_stats.new_vocab_count + %s,
            avg_formality_score   = %s,
            username              = %s
    """, (
        discord_id, username, stat_date,
        0 if has_error else 1, 1 if has_error else 0,
        new_vocab_count, new_avg,
        # ON CONFLICT values
        0 if has_error else 1, 1 if has_error else 0,
        new_vocab_count, new_avg, username
    ))
    conn.commit()
    cur.close()
    conn.close()


def get_daily_stats(stat_date):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM daily_stats WHERE stat_date = %s ORDER BY total_messages DESC
    """, (stat_date,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_recent_messages(discord_id, limit=30):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT original_text, has_error, error_types FROM messages_log
        WHERE discord_id = %s
        ORDER BY created_at DESC
        LIMIT %s
    """, (discord_id, limit))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def save_cefr_estimate(discord_id, username, estimated_level):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO cefr_estimates (discord_id, username, estimated_level)
        VALUES (%s, %s, %s)
    """, (discord_id, username, estimated_level))
    conn.commit()
    cur.close()
    conn.close()


def get_latest_cefr(discord_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT estimated_level, estimated_at FROM cefr_estimates
        WHERE discord_id = %s
        ORDER BY estimated_at DESC
        LIMIT 1
    """, (discord_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


# ── Generated vocab helpers ──────────────────────────────────────────────────

def get_all_used_words():
    """Return a set of all words already generated (to avoid repetition)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT word FROM generated_vocab;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {row["word"].lower() for row in rows}


def save_generated_vocab_batch(words: list, generated_on: date):
    """
    words: list of dicts with keys: word, topic, word_type, meaning
    Inserts with ON CONFLICT DO NOTHING to safely handle duplicates.
    """
    conn = get_connection()
    cur = conn.cursor()
    for w in words:
        cur.execute("""
            INSERT INTO generated_vocab (word, topic, word_type, meaning, generated_on)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (word) DO NOTHING
        """, (w["word"].lower(), w.get("topic", ""), w.get("word_type", ""), w.get("meaning", ""), generated_on))
    conn.commit()
    cur.close()
    conn.close()


def get_todays_generated_vocab(today: date):
    """Return words already generated today (to avoid regenerating on restart)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT word, topic, word_type, meaning FROM generated_vocab
        WHERE generated_on = %s
    """, (today,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return list(rows)

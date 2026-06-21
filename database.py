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
    """Open a new connection to the Postgres database."""
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
            messages_with_errors INTEGER DEFAULT 0,
            new_vocab_count INTEGER DEFAULT 0,
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

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Database tables ready.")


def log_message(discord_id, username, channel_id, original_text, corrected_text,
                 natural_rewrite, has_error, error_types):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO messages_log
        (discord_id, username, channel_id, original_text, corrected_text,
         natural_rewrite, has_error, error_types)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (discord_id, username, channel_id, original_text, corrected_text,
          natural_rewrite, has_error, json.dumps(error_types or [])))
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


def upsert_daily_stat(discord_id, username, stat_date, has_error, new_vocab_count=0):
    """Increment today's stat row for a user (creates it if it doesn't exist)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO daily_stats (discord_id, username, stat_date, total_messages,
                                  messages_with_errors, new_vocab_count)
        VALUES (%s, %s, %s, 1, %s, %s)
        ON CONFLICT (discord_id, stat_date)
        DO UPDATE SET
            total_messages = daily_stats.total_messages + 1,
            messages_with_errors = daily_stats.messages_with_errors + %s,
            new_vocab_count = daily_stats.new_vocab_count + %s,
            username = %s
    """, (discord_id, username, stat_date, 1 if has_error else 0, new_vocab_count,
          1 if has_error else 0, new_vocab_count, username))
    conn.commit()
    cur.close()
    conn.close()


def get_daily_stats(stat_date):
    """Return all users' stats for a given date."""
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
    """Used for CEFR level estimation — pulls recent messages for a user."""
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

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
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'UTC';")
    return conn


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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS deploy_announcements (
            id SERIAL PRIMARY KEY,
            deploy_key TEXT NOT NULL UNIQUE,
            message TEXT,
            announced_at TIMESTAMP DEFAULT NOW()
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

    # One active personalised translation exercise per learner.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS practice_sessions (
            discord_id TEXT PRIMARY KEY,
            username TEXT,
            channel_id TEXT NOT NULL,
            round_number INTEGER NOT NULL DEFAULT 1,
            variant TEXT NOT NULL,
            level TEXT NOT NULL,
            context TEXT NOT NULL,
            vietnamese_prompt TEXT NOT NULL,
            awaiting_answer BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # Attempt history lets the tutor adapt later rounds to recurring mistakes.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS practice_attempts (
            id SERIAL PRIMARY KEY,
            discord_id TEXT NOT NULL,
            username TEXT,
            round_number INTEGER NOT NULL,
            variant TEXT NOT NULL,
            level TEXT NOT NULL,
            context TEXT NOT NULL,
            vietnamese_prompt TEXT NOT NULL,
            learner_answer TEXT NOT NULL,
            overall_score REAL,
            grammar_score REAL,
            vocabulary_score REAL,
            naturalness_score REAL,
            native_like_score REAL,
            error_summary TEXT,
            feedback_markdown TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # One shared exercise per Discord thread, created manually or by the daily schedule.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_practice_prompts (
            id SERIAL PRIMARY KEY,
            schedule_key TEXT NOT NULL UNIQUE,
            prompt_message_id TEXT NOT NULL UNIQUE,
            channel_id TEXT NOT NULL,
            variant TEXT NOT NULL,
            level TEXT NOT NULL,
            context TEXT NOT NULL,
            vietnamese_prompt TEXT NOT NULL,
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
        ADD COLUMN IF NOT EXISTS total_messages INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS messages_correct INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS messages_with_errors INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS new_vocab_count INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS avg_formality_score REAL DEFAULT NULL;
    """)

    cur.execute("""
        WITH grouped AS (
            SELECT
                MIN(id) AS keep_id,
                discord_id,
                stat_date,
                SUM(total_messages) AS total_messages,
                SUM(messages_correct) AS messages_correct,
                SUM(messages_with_errors) AS messages_with_errors,
                SUM(new_vocab_count) AS new_vocab_count,
                AVG(avg_formality_score) FILTER (WHERE avg_formality_score IS NOT NULL) AS avg_formality_score,
                COUNT(*) AS row_count
            FROM daily_stats
            GROUP BY discord_id, stat_date
            HAVING COUNT(*) > 1
        )
        UPDATE daily_stats d
        SET
            total_messages = grouped.total_messages,
            messages_correct = grouped.messages_correct,
            messages_with_errors = grouped.messages_with_errors,
            new_vocab_count = grouped.new_vocab_count,
            avg_formality_score = grouped.avg_formality_score
        FROM grouped
        WHERE d.id = grouped.keep_id;
    """)

    cur.execute("""
        WITH grouped AS (
            SELECT MIN(id) AS keep_id, discord_id, stat_date
            FROM daily_stats
            GROUP BY discord_id, stat_date
            HAVING COUNT(*) > 1
        )
        DELETE FROM daily_stats d
        USING grouped
        WHERE d.discord_id = grouped.discord_id
          AND d.stat_date = grouped.stat_date
          AND d.id <> grouped.keep_id;
    """)

    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS daily_stats_discord_id_stat_date_idx
        ON daily_stats (discord_id, stat_date);
    """)

    cur.execute("""
        ALTER TABLE generated_vocab
        ADD COLUMN IF NOT EXISTS topic TEXT,
        ADD COLUMN IF NOT EXISTS word_type TEXT,
        ADD COLUMN IF NOT EXISTS meaning TEXT,
        ADD COLUMN IF NOT EXISTS generated_on DATE,
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS practice_attempts_discord_id_created_at_idx
        ON practice_attempts (discord_id, created_at DESC);
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Database tables ready.")


def claim_deploy_announcement(deploy_key, message):
    """
    Return True only the first time a deploy key is seen.

    This keeps deploy announcements from repeating on reconnects or restarts
    for the same deployed commit.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO deploy_announcements (deploy_key, message)
        VALUES (%s, %s)
        ON CONFLICT (deploy_key) DO NOTHING
        RETURNING id
    """, (deploy_key, message))
    inserted = cur.fetchone() is not None
    conn.commit()
    cur.close()
    conn.close()
    return inserted


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
    elif existing:
        new_avg = existing["avg_formality_score"]
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


def get_activity_stats_between(start_at, end_at):
    """
    Build report stats directly from messages_log for a time window.

    This is more reliable than daily_stats for reports because it can recover
    from older bugs, partial stat writes, and timezone mismatches.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        WITH period_messages AS (
            SELECT discord_id, username, has_error, formality_score, created_at
            FROM messages_log
            WHERE created_at >= %s AND created_at < %s
        ),
        latest_names AS (
            SELECT DISTINCT ON (discord_id)
                discord_id,
                username
            FROM period_messages
            ORDER BY discord_id, created_at DESC
        ),
        message_stats AS (
            SELECT
                discord_id,
                COUNT(*)::INTEGER AS total_messages,
                SUM(CASE WHEN has_error IS FALSE THEN 1 ELSE 0 END)::INTEGER AS messages_correct,
                SUM(CASE WHEN has_error IS TRUE THEN 1 ELSE 0 END)::INTEGER AS messages_with_errors,
                AVG(formality_score) AS avg_formality_score
            FROM period_messages
            GROUP BY discord_id
        ),
        vocab_stats AS (
            SELECT
                discord_id,
                COUNT(*)::INTEGER AS new_vocab_count
            FROM vocab_bank
            WHERE created_at >= %s AND created_at < %s
            GROUP BY discord_id
        )
        SELECT
            m.discord_id,
            COALESCE(NULLIF(n.username, ''), m.discord_id) AS username,
            m.total_messages,
            m.messages_correct,
            m.messages_with_errors,
            COALESCE(v.new_vocab_count, 0)::INTEGER AS new_vocab_count,
            m.avg_formality_score
        FROM message_stats m
        LEFT JOIN latest_names n ON n.discord_id = m.discord_id
        LEFT JOIN vocab_stats v ON v.discord_id = m.discord_id
        ORDER BY m.total_messages DESC
    """, (start_at, end_at, start_at, end_at))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_error_summary_between(discord_id: str, start_at, end_at) -> dict:
    """
    Return aggregated error type counts for a user in a report window.

    The report itself is built from messages_log over a rolling 24-hour UTC
    window, so this uses the same bounds instead of DATE(created_at).
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT error_types FROM messages_log
        WHERE discord_id = %s
          AND has_error IS TRUE
          AND created_at >= %s
          AND created_at < %s
          AND error_types IS NOT NULL
          AND error_types != '[]'
    """, (discord_id, start_at, end_at))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    counts = {}
    for row in rows:
        try:
            types = json.loads(row["error_types"]) if isinstance(row["error_types"], str) else row["error_types"]
            for error_type in types:
                counts[error_type] = counts.get(error_type, 0) + 1
        except Exception:
            pass
    return counts


def get_recent_messages(discord_id, limit=30):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT original_text, has_error, error_types FROM messages_log
        WHERE discord_id = %s
          AND has_error IS NOT NULL
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


# ── Translation practice helpers ─────────────────────────────────────────────

def save_practice_session(discord_id, username, channel_id, round_number,
                          variant, level, context, vietnamese_prompt):
    """Create or replace the exercise awaiting a learner's next answer."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO practice_sessions (
            discord_id, username, channel_id, round_number, variant, level,
            context, vietnamese_prompt, awaiting_answer, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, NOW())
        ON CONFLICT (discord_id)
        DO UPDATE SET
            username = EXCLUDED.username,
            channel_id = EXCLUDED.channel_id,
            round_number = EXCLUDED.round_number,
            variant = EXCLUDED.variant,
            level = EXCLUDED.level,
            context = EXCLUDED.context,
            vietnamese_prompt = EXCLUDED.vietnamese_prompt,
            awaiting_answer = TRUE,
            updated_at = NOW()
    """, (
        discord_id, username, channel_id, round_number, variant, level,
        context, vietnamese_prompt,
    ))
    conn.commit()
    cur.close()
    conn.close()


def claim_practice_session(discord_id, channel_id):
    """Atomically claim an awaiting exercise so an answer is graded once."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE practice_sessions
        SET awaiting_answer = FALSE, updated_at = NOW()
        WHERE discord_id = %s
          AND channel_id = %s
          AND awaiting_answer IS TRUE
        RETURNING round_number, variant, level, context, vietnamese_prompt
    """, (discord_id, channel_id))
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return row


def restore_practice_session(discord_id, channel_id):
    """Allow the learner to retry when AI grading fails."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE practice_sessions
        SET awaiting_answer = TRUE, updated_at = NOW()
        WHERE discord_id = %s AND channel_id = %s
    """, (discord_id, channel_id))
    conn.commit()
    cur.close()
    conn.close()


def get_next_practice_round(discord_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT COALESCE(MAX(round_number), 0) + 1 AS next_round
        FROM practice_attempts
        WHERE discord_id = %s
    """, (discord_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return int(row["next_round"] if row else 1)


def get_recent_practice_attempts(discord_id, limit=5):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT round_number, variant, level, context, overall_score, error_summary
        FROM practice_attempts
        WHERE discord_id = %s
        ORDER BY created_at DESC
        LIMIT %s
    """, (discord_id, limit))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def save_practice_attempt(discord_id, username, round_number, challenge,
                          learner_answer, result):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO practice_attempts (
            discord_id, username, round_number, variant, level, context,
            vietnamese_prompt, learner_answer, overall_score, grammar_score,
            vocabulary_score, naturalness_score, native_like_score,
            error_summary, feedback_markdown
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
    """, (
        discord_id,
        username,
        round_number,
        challenge["variant"],
        challenge["level"],
        challenge["context"],
        challenge["vietnamese_prompt"],
        learner_answer,
        result["overall_score"],
        result["grammar_score"],
        result["vocabulary_score"],
        result["naturalness_score"],
        result["native_like_score"],
        result["error_summary"],
        result["feedback_markdown"],
    ))
    conn.commit()
    cur.close()
    conn.close()


def scheduled_practice_exists(schedule_key):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT 1 FROM scheduled_practice_prompts WHERE schedule_key = %s LIMIT 1
    """, (schedule_key,))
    exists = cur.fetchone() is not None
    cur.close()
    conn.close()
    return exists


def save_practice_thread_prompt(prompt_key, prompt_message_id, channel_id,
                                variant, level, context, vietnamese_prompt):
    """Persist the one shared exercise associated with a Discord thread."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO scheduled_practice_prompts (
            schedule_key, prompt_message_id, channel_id, variant, level,
            context, vietnamese_prompt
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (schedule_key) DO NOTHING
    """, (
        prompt_key, prompt_message_id, channel_id, variant, level, context,
        vietnamese_prompt,
    ))
    conn.commit()
    cur.close()
    conn.close()


def get_scheduled_practice(prompt_message_id, channel_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT variant, level, context, vietnamese_prompt
        FROM scheduled_practice_prompts
        WHERE prompt_message_id = %s AND channel_id = %s
        LIMIT 1
    """, (prompt_message_id, channel_id))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def get_practice_thread_prompt(thread_id):
    """Return the one shared exercise hosted by a practice thread."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT variant, level, context, vietnamese_prompt
        FROM scheduled_practice_prompts
        WHERE channel_id = %s
        ORDER BY created_at DESC
        LIMIT 1
    """, (thread_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

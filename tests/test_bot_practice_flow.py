import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch


os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

import bot as bot_module


SHARED_CHALLENGE = {
    "variant": "British English",
    "level": "Intermediate / Social conversation",
    "context": "Rủ một người bạn đi uống cà phê.",
    "vietnamese_prompt": "Chiều nay cậu có muốn đi uống cà phê không?",
}

REVIEW_RESULT = {
    "overall_score": 8.0,
    "grammar_score": 8.0,
    "vocabulary_score": 8.0,
    "naturalness_score": 8.0,
    "native_like_score": 8.0,
    "error_summary": "Cần dùng collocation tự nhiên hơn.",
    "feedback_markdown": "## Câu của tôi\n\n# Điểm: 8/10",
}


class FakeThread:
    def __init__(self, thread_id=700):
        self.id = thread_id
        self.sent = []

    async def send(self, content):
        self.sent.append(content)


class FakeAnswer:
    def __init__(self, user_id, display_name, mention, content, channel):
        self.author = SimpleNamespace(
            id=user_id,
            display_name=display_name,
            mention=mention,
        )
        self.channel = channel
        self.content = content
        self.reactions = []
        self.replies = []

    async def add_reaction(self, reaction):
        self.reactions.append(reaction)

    async def reply(self, content, **kwargs):
        self.replies.append(content)


class SharedPracticeFlowTests(unittest.IsolatedAsyncioTestCase):
    def test_same_thread_prompt_is_resolved_for_multiple_users(self):
        prompt_row = dict(SHARED_CHALLENGE)

        with patch.object(
            bot_module.db,
            "get_practice_thread_prompt",
            return_value=prompt_row,
        ), patch.object(
            bot_module.db,
            "get_next_practice_round",
            side_effect=[1, 4],
        ):
            first = bot_module.get_practice_for_message("user-1", "thread-1")
            second = bot_module.get_practice_for_message("user-2", "thread-1")

        self.assertEqual(first[0], SHARED_CHALLENGE)
        self.assertEqual(second[0], SHARED_CHALLENGE)
        self.assertEqual(first[1], 1)
        self.assertEqual(second[1], 4)

    async def test_each_users_feedback_tags_that_user_without_a_next_exercise(self):
        thread = FakeThread()
        first = FakeAnswer(1, "Alice", "<@1>", "Do you want to get coffee?", thread)
        second = FakeAnswer(2, "Bob", "<@2>", "Would you like to have coffee?", thread)
        saved_attempts = []

        with patch.object(
            bot_module.db,
            "get_recent_practice_attempts",
            return_value=[],
        ), patch.object(
            bot_module.db,
            "save_practice_attempt",
            side_effect=lambda *args: saved_attempts.append(args),
        ), patch.object(
            bot_module,
            "review_translation",
            return_value=REVIEW_RESULT,
        ):
            await bot_module.handle_practice_answer(first, SHARED_CHALLENGE, 1)
            await bot_module.handle_practice_answer(second, SHARED_CHALLENGE, 1)

        self.assertEqual(len(saved_attempts), 2)
        self.assertTrue(first.replies[0].startswith("<@1>"))
        self.assertTrue(second.replies[0].startswith("<@2>"))
        self.assertNotIn("Round", first.replies[0])
        self.assertNotIn("Round", second.replies[0])
        self.assertEqual(first.reactions, ["⏳", "✅"])
        self.assertEqual(second.reactions, ["⏳", "✅"])


if __name__ == "__main__":
    unittest.main()

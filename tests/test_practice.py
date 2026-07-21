import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import practice as practice_module
from practice import (
    _parse_send_hours,
    create_practice_thread,
    format_challenge,
    format_review_with_next,
    generate_challenge,
    review_translation,
    send_scheduled_practice,
    split_discord_message,
)


class FakeCompletions:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = self.payloads.pop(0)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
                )
            ]
        )


class FakeClient:
    def __init__(self, payloads):
        self.chat = SimpleNamespace(completions=FakeCompletions(payloads))


class FakeMessage:
    def __init__(self, message_id=123):
        self.id = message_id
        self.reactions = []
        self.thread = None
        self.thread_options = None

    async def add_reaction(self, reaction):
        self.reactions.append(reaction)

    async def create_thread(self, **kwargs):
        self.thread_options = kwargs
        self.thread = FakeThread(name=kwargs["name"])
        return self.thread


class FakeThread:
    def __init__(self, name, thread_id=789):
        self.name = name
        self.id = thread_id
        self.sent = []
        self.messages = []
        self.added_users = []

    async def send(self, content):
        self.sent.append(content)
        message = FakeMessage(message_id=900 + len(self.messages))
        self.messages.append(message)
        return message

    async def add_user(self, user):
        self.added_users.append(user)


class FakeChannel:
    def __init__(self, name="chat-en", channel_id=456):
        self.name = name
        self.id = channel_id
        self.sent = []
        self.messages = []

    async def send(self, content):
        self.sent.append(content)
        message = FakeMessage(message_id=123 + len(self.messages))
        self.messages.append(message)
        return message


class FakePracticeDB:
    def __init__(self):
        self.saved = []

    def scheduled_practice_exists(self, schedule_key):
        return any(row["schedule_key"] == schedule_key for row in self.saved)

    def save_scheduled_practice(self, **kwargs):
        self.saved.append(kwargs)


class PracticeTests(unittest.TestCase):
    def test_default_local_send_hours_are_9_14_and_21(self):
        self.assertEqual(_parse_send_hours("9,14,21"), (9, 14, 21))

    def test_invalid_send_hours_fall_back_to_9_14_and_21(self):
        self.assertEqual(_parse_send_hours("invalid"), (9, 14, 21))

    def test_generate_challenge_starts_with_british_english(self):
        client = FakeClient([
            {
                "variant": "British English",
                "level": "Casual / Everyday life",
                "context": "Bạn đang rủ bạn đi uống cà phê.",
                "vietnamese_prompt": "Chiều nay cậu có muốn đi uống cà phê không?",
            }
        ])

        challenge = generate_challenge(client, round_number=1)

        self.assertEqual(challenge["variant"], "British English")
        self.assertIn("cà phê", challenge["vietnamese_prompt"])
        request = client.chat.completions.calls[0]
        self.assertEqual(request["response_format"], {"type": "json_object"})

    def test_review_keeps_feedback_separate_from_next_prompt(self):
        next_challenge = {
            "variant": "American English",
            "level": "Workplace / Intermediate",
            "context": "Bạn báo với đồng nghiệp rằng sẽ trễ cuộc họp.",
            "vietnamese_prompt": "Nhắn giúp tôi là tôi sẽ đến muộn khoảng mười phút.",
        }
        client = FakeClient([
            {
                "overall_score": 8,
                "grammar_score": 9,
                "vocabulary_score": 8,
                "naturalness_score": 7.5,
                "native_like_score": 7,
                "error_summary": "Cần dùng collocation tự nhiên hơn.",
                "feedback_markdown": "## Câu của tôi\n> Do you want drink coffee?\n\n# Điểm: 8/10",
                "next_challenge": next_challenge,
            }
        ])
        challenge = {
            "variant": "British English",
            "level": "Casual / Everyday life",
            "context": "Rủ bạn đi uống cà phê.",
            "vietnamese_prompt": "Cậu có muốn đi uống cà phê không?",
        }

        result = review_translation(client, challenge, "Do you want drink coffee?", 1)
        output = format_review_with_next(result, 2)

        self.assertEqual(result["overall_score"], 8.0)
        self.assertIn("### Round 2 - 🇺🇸 American English", output)
        self.assertIn(next_challenge["vietnamese_prompt"], output)

    def test_daily_format_requires_an_answer_in_the_thread(self):
        challenge = {
            "variant": "Australian English",
            "level": "Social / Intermediate",
            "context": "Nói chuyện với một người bạn.",
            "vietnamese_prompt": "Dạo này công việc của cậu thế nào?",
        }

        output = format_challenge(challenge, daily=True)

        self.assertIn("Daily Practice", output)
        self.assertIn("trong thread này", output)
        self.assertNotIn("How has work", output)

    def test_long_feedback_is_split_under_discord_limit(self):
        content = ("Đoạn phản hồi dài. " * 250).strip()

        chunks = split_discord_message(content, limit=300)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 300 for chunk in chunks))
        self.assertEqual(" ".join(chunks), content)


class ScheduledPracticeTests(unittest.IsolatedAsyncioTestCase):
    async def test_thread_adds_participant_and_limits_its_name(self):
        starter = FakeMessage()
        participant = SimpleNamespace(id=42)

        thread = await create_practice_thread(
            starter,
            name="P" * 120,
            participant=participant,
        )

        self.assertEqual(len(starter.thread_options["name"]), 100)
        self.assertEqual(starter.thread_options["auto_archive_duration"], 1440)
        self.assertEqual(thread.added_users, [participant])

    async def test_scheduled_prompt_is_saved_and_not_posted_twice(self):
        challenge = {
            "variant": "British English",
            "level": "Casual / Everyday life",
            "context": "Bạn đang nói chuyện với một người bạn.",
            "vietnamese_prompt": "Hôm nay cậu thấy thế nào?",
        }
        client = FakeClient([challenge])
        channel = FakeChannel()
        bot = SimpleNamespace(
            guilds=[SimpleNamespace(text_channels=[channel])]
        )
        fake_db = FakePracticeDB()
        send_hour = practice_module.PRACTICE_SEND_HOURS_LOCAL[0]
        local_now = datetime(2026, 7, 20, send_hour, 0)

        with patch.object(practice_module, "_database", return_value=fake_db):
            first_send = await send_scheduled_practice(
                bot,
                client,
                "chat-en",
                local_now,
            )
            duplicate_send = await send_scheduled_practice(
                bot,
                client,
                "chat-en",
                local_now,
            )

        self.assertTrue(first_send)
        self.assertFalse(duplicate_send)
        self.assertEqual(len(channel.sent), 1)
        self.assertIn("@everyone", channel.sent[0])
        thread = channel.messages[0].thread
        self.assertIsNotNone(thread)
        self.assertEqual(len(thread.sent), 1)
        self.assertEqual(len(fake_db.saved), 1)
        self.assertEqual(fake_db.saved[0]["channel_id"], str(thread.id))
        self.assertIn("trong thread này", thread.sent[0])
        self.assertEqual(thread.messages[0].reactions, ["✍️"])


if __name__ == "__main__":
    unittest.main()

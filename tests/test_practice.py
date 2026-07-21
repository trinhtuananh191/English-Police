import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import practice as practice_module
from practice import (
    _parse_send_hours,
    _random_hints,
    create_practice_thread,
    format_challenge,
    format_thread_prompt,
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
        return any(row["prompt_key"] == schedule_key for row in self.saved)

    def save_practice_thread_prompt(self, **kwargs):
        self.saved.append(kwargs)


class PracticeTests(unittest.TestCase):
    def test_default_local_send_hours_are_9_14_and_21(self):
        self.assertEqual(_parse_send_hours("9,14,21"), (9, 14, 21))

    def test_invalid_send_hours_fall_back_to_9_14_and_21(self):
        self.assertEqual(_parse_send_hours("invalid"), (9, 14, 21))

    def test_generate_challenge_uses_random_variant_topic_and_level(self):
        client = FakeClient([
            {
                "variant": "American English",
                "level": "Advanced / Formal communication",
                "context": "Bạn đang trình bày quan điểm về công nghệ.",
                "vietnamese_prompt": "Theo tôi, công nghệ này cần được kiểm soát chặt chẽ hơn.",
            }
        ])

        with patch.object(
            practice_module.random,
            "choice",
            side_effect=["American English", "Công nghệ", "Advanced / Formal communication"],
        ):
            challenge = generate_challenge(client)

        self.assertEqual(challenge["variant"], "American English")
        request = client.chat.completions.calls[0]
        self.assertEqual(request["response_format"], {"type": "json_object"})
        prompt = request["messages"][1]["content"]
        self.assertIn("Required topic: Công nghệ", prompt)
        self.assertIn("Required level: Advanced / Formal communication", prompt)

    def test_review_returns_feedback_without_another_exercise(self):
        client = FakeClient([
            {
                "overall_score": 8,
                "grammar_score": 9,
                "vocabulary_score": 8,
                "naturalness_score": 7.5,
                "native_like_score": 7,
                "error_summary": "Cần dùng collocation tự nhiên hơn.",
                "feedback_markdown": "## Câu của tôi\n> Do you want drink coffee?\n\n# Điểm: 8/10",
            }
        ])
        challenge = {
            "variant": "British English",
            "level": "Casual / Everyday life",
            "context": "Rủ bạn đi uống cà phê.",
            "vietnamese_prompt": "Cậu có muốn đi uống cà phê không?",
        }

        result = review_translation(client, challenge, "Do you want drink coffee?", 1)

        self.assertEqual(result["overall_score"], 8.0)
        self.assertNotIn("next_challenge", result)
        request_payload = client.chat.completions.calls[0]["messages"][1]["content"]
        self.assertNotIn("next_topic_hint", request_payload)
        self.assertNotIn("next_variant_hint", request_payload)

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

    def test_thread_prompt_combines_everyone_mention_and_challenge(self):
        challenge = {
            "variant": "British English",
            "level": "Casual / Everyday life",
            "context": "Rủ bạn đi uống cà phê.",
            "vietnamese_prompt": "Cậu có muốn đi uống cà phê không?",
        }

        output = format_thread_prompt(
            challenge,
            round_number=1,
            announcement="Bài luyện tập của <@42>",
        )

        self.assertIn("@everyone", output)
        self.assertIn("<@42>", output)
        self.assertIn("### Practice", output)
        self.assertIn(challenge["vietnamese_prompt"], output)

    def test_random_hints_select_all_three_dimensions(self):
        with patch.object(
            practice_module.random,
            "choice",
            side_effect=["Canadian English", "Du lịch", "Intermediate / Social conversation"],
        ):
            hints = _random_hints()

        self.assertEqual(
            hints,
            ("Canadian English", "Du lịch", "Intermediate / Social conversation"),
        )

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
        self.assertIn("Daily Practice", channel.sent[0])
        self.assertIn(challenge["vietnamese_prompt"], channel.sent[0])
        thread = channel.messages[0].thread
        self.assertIsNotNone(thread)
        self.assertEqual(len(thread.sent), 0)
        self.assertEqual(len(fake_db.saved), 1)
        self.assertEqual(fake_db.saved[0]["channel_id"], str(thread.id))
        self.assertEqual(channel.messages[0].reactions, ["✍️"])

    async def test_scheduler_does_nothing_outside_daily_hours(self):
        client = FakeClient([])
        channel = FakeChannel()
        bot = SimpleNamespace(guilds=[SimpleNamespace(text_channels=[channel])])
        local_now = datetime(2026, 7, 20, 10, 0)

        sent = await send_scheduled_practice(
            bot,
            client,
            "chat-en",
            local_now,
        )

        self.assertFalse(sent)
        self.assertEqual(channel.sent, [])
        self.assertEqual(client.chat.completions.calls, [])


if __name__ == "__main__":
    unittest.main()

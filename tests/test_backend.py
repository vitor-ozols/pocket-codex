import unittest

from pocket_codex.backend import _history_messages


class HistoryTests(unittest.TestCase):
    def test_history_keeps_only_user_and_final_answer(self) -> None:
        response = {
            "thread": {
                "turns": [
                    {
                        "items": [
                            {
                                "type": "userMessage",
                                "content": [{"type": "text", "text": "question"}],
                            },
                            {
                                "type": "agentMessage",
                                "phase": "MessagePhase.commentary",
                                "text": "internal update",
                            },
                            {"type": "fileChange", "changes": []},
                            {
                                "type": "agentMessage",
                                "phase": "MessagePhase.final_answer",
                                "text": "answer",
                            },
                        ]
                    }
                ]
            }
        }

        self.assertEqual(
            _history_messages(response),
            [
                {"role": "user", "text": "question"},
                {"role": "assistant", "text": "answer"},
            ],
        )


if __name__ == "__main__":
    unittest.main()

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from pocket_codex.backend import CodexWorker, _history_messages


class HistoryTests(unittest.TestCase):
    def test_model_effort_selection_updates_both_values(self) -> None:
        worker = CodexWorker(".")
        worker._cmd_model_effort("gpt-test::high")

        self.assertEqual(worker.model, "gpt-test")
        self.assertEqual(worker.effort, "high")

    def test_catalog_uses_runnable_model_instead_of_catalog_id(self) -> None:
        worker = CodexWorker(".")
        worker._client = Mock()
        worker._client.models.return_value = {"data": [
            {"id": "catalog-id", "model": "runnable-model", "display_name": "Test",
             "supported_reasoning_efforts": [{"reasoning_effort": "high"}, {"reasoning_effort": "xhigh"}],
             "default_reasoning_effort": "high"}
        ]}
        worker._cmd_models("")
        model = worker.events.get_nowait().data[0]
        self.assertEqual(model["id"], "runnable-model")
        self.assertEqual(model["efforts"], ["high", "xhigh"])
        self.assertEqual(model["default_effort"], "high")

    def test_streams_messages_and_tool_activity_without_reasoning(self) -> None:
        worker = CodexWorker(".")
        worker._thread = Mock()
        worker.model = "selected-model"
        worker._sandbox = {"write": "workspace-write"}
        def event(method, **payload):
            return SimpleNamespace(method=method, payload=payload)
        worker._thread.turn.return_value.stream.return_value = iter([
            event("item/started", item={"root": {"type": "reasoning"}}),
            event("item/started", item={"type": "commandExecution", "command": "ls"}),
            event("item/commandExecution/outputDelta", delta="file.txt"),
            event("item/started", item={"type": "agentMessage", "id": "msg", "phase": "final_answer"}),
            event("item/agentMessage/delta", item_id="msg", delta="Hello"),
            event("item/completed", item={"type": "agentMessage", "id": "msg", "text": "Hello!", "phase": "final_answer"}),
            event("turn/completed", turn={"status": "completed"}),
        ])
        worker._ask("hi")
        events = list(worker.events.queue)
        self.assertEqual([e.text for e in events if e.kind == "message_delta"], ["Hello"])
        self.assertEqual([e.text for e in events if e.kind == "answer"], ["Hello!"])
        self.assertEqual(len([e for e in events if e.kind == "activity"]), 2)
        self.assertEqual(worker._thread.turn.call_args.kwargs["model"], "selected-model")

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

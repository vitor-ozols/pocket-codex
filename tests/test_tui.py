import asyncio
import queue
import unittest

from pocket_codex.backend import Event
from textual.widgets import ListView

from pocket_codex.tui import ChatBubble, Composer, PocketCodexApp


class FakeWorker:
    def __init__(self) -> None:
        self.cwd = "/tmp"
        self.model = None
        self.busy = False
        self.events: queue.Queue[Event] = queue.Queue()
        self.commands = []
        self.prompts = []

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass

    def command(self, command: object) -> bool:
        self.commands.append(command)
        return True

    def ask(self, prompt: str) -> bool:
        self.prompts.append(prompt)
        return True

    def interrupt(self) -> bool:
        return False


class TuiTests(unittest.IsolatedAsyncioTestCase):
    async def test_narrow_layout_and_prompt_submission(self) -> None:
        worker = FakeWorker()
        app = PocketCodexApp("/tmp", worker=worker)

        async with app.run_test(size=(40, 30)) as pilot:
            await pilot.pause()
            self.assertTrue(app.screen.has_class("narrow"))

            await pilot.press("ctrl+b")
            self.assertTrue(app.screen.has_class("sidebar-open"))
            self.assertIsInstance(app.focused, ListView)

            composer = app.query_one("#prompt", Composer)
            composer.load_text("hello")
            composer.focus()
            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(worker.prompts, ["hello"])
            self.assertEqual(len(app.query(ChatBubble)), 1)
            self.assertFalse(app.query_one("#thinking").has_class("hidden"))

    async def test_backend_events_populate_models_and_threads(self) -> None:
        worker = FakeWorker()
        app = PocketCodexApp("/tmp", worker=worker)

        async with app.run_test(size=(100, 35)) as pilot:
            worker.events.put(
                Event(
                    "models",
                    data=[{"id": "model-a", "name": "Model A", "default": True}],
                )
            )
            worker.events.put(
                Event("threads", data=[{"id": "thr_1", "name": "First chat"}])
            )
            await asyncio.sleep(0.15)
            await pilot.pause()

            self.assertFalse(app.screen.has_class("narrow"))
            self.assertEqual(str(app.query_one("#model-select").value), "model-a")
            self.assertEqual(len(app.query("#thread-list ListItem")), 1)


if __name__ == "__main__":
    unittest.main()

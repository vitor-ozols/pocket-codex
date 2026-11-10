import unittest
from unittest.mock import patch
from pocket_codex.backend import Event
from pathlib import Path
from pocket_codex.commands import Command

from pocket_codex.ascii_tui import (
    AsciiTUI,
    Message,
    ascii_only,
    colorize,
    content_left,
    next_panel,
    parse_cli_args,
    wrap_messages,
)


class AsciiTuiTests(unittest.TestCase):
    def test_stream_is_visible_before_completion_and_not_duplicated(self) -> None:
        tui = AsciiTUI(".")
        tui._event(Event("status", "thinking"))
        tui._event(Event("message_delta", "Hello", {"id": "m"}))
        self.assertEqual(tui.messages[-1].text, "Hello")
        rows = tui._body_lines(24, 8)
        self.assertIn(("assistant", "< Hello"), rows)
        self.assertTrue(any("Working" in row for _, row in rows))
        tui._event(Event("message_delta", " world", {"id": "m"}))
        tui._event(Event("message_complete", "Hello world!", {"id": "m"}))
        tui._event(Event("answer", "Hello world!", {"streamed": True}))
        tui._event(Event("idle", "ready"))
        self.assertEqual([m.text for m in tui.messages if m.role == "assistant"], ["Hello world!"])

    def test_working_log_is_bounded_scrollable_and_visible_in_small_frame(self) -> None:
        tui = AsciiTUI(".")
        tui._event(Event("status", "thinking"))
        for i in range(205):
            tui._event(Event("activity", f"command output {i}"))
        self.assertEqual(len(tui.working), 200)
        frames = []
        tui._render_frame = lambda frame, width, height: frames.append(frame)
        with patch("pocket_codex.ascii_tui.shutil.get_terminal_size", return_value=(24, 10)):
            tui._draw()
        self.assertEqual(len(frames[0]), 10)
        self.assertTrue(any("Working" in line for line in frames[0]))
        self.assertTrue(any("output 204" in line for line in frames[0]))
        tui._key("\x17")
        self.assertEqual(tui.panel, "working")
        rows = tui._body_lines(24, 6)
        self.assertTrue(any("204" in line for _, line in rows))
        tui._key("PGUP")
        self.assertFalse(any("204" in line for _, line in tui._body_lines(24, 6)))
        tui._key("\x17")
        self.assertEqual(tui.panel, "chat")

    def test_stream_preserves_manual_scroll_and_handles_interleaved_items(self) -> None:
        tui = AsciiTUI(".")
        tui._event(Event("message_delta", "First", {"id": "one"}))
        tui._event(Event("message_delta", "Second", {"id": "two"}))
        tui.scroll = 3
        tui._event(Event("message_complete", "First!", {"id": "one"}))
        self.assertEqual(tui.scroll, 3)
        self.assertEqual([m.text for m in tui.messages[-2:]], ["First!", "Second"])
        tui._event(Event("activity", "bad\x1b[2J"))
        self.assertNotIn("\x1b", tui.working[-1].text)

    def test_drain_yields_to_render_and_accepts_legacy_answers(self) -> None:
        tui = AsciiTUI(".")
        for _ in range(150):
            tui.agent.events.put(Event("message_delta", "a", {"id": "m"}))
        tui._drain_events()
        self.assertEqual(len(tui.messages[-1].text), 100)
        self.assertEqual(tui.agent.events.qsize(), 50)
        tui._event(Event("answer", "legacy answer"))
        self.assertEqual(tui.messages[-1].text, "legacy answer")

    def test_ascii_only_transliterates_and_replaces_symbols(self) -> None:
        self.assertEqual(
            ascii_only("a\u00e7\u00e3o \u2192 pronta \u2014 ok"), "acao -> pronta - ok"
        )
        self.assertEqual(ascii_only("cafe"), "cafe")

    def test_wrapped_output_contains_only_ascii(self) -> None:
        lines = wrap_messages([Message("assistant", "resposta \u2022 util")], 12)
        rendered = "\n".join(line for _, line in lines)
        self.assertTrue(rendered.isascii())
        self.assertIn("*", rendered)

    def test_prefix_is_only_used_on_first_line(self) -> None:
        lines = wrap_messages([Message("user", "one two three")], 8)
        self.assertEqual(lines[:2], [("user", "> one"), ("user", "  two")])

    def test_wrapping_can_use_inner_content_width(self) -> None:
        lines = wrap_messages([Message("assistant", "alpha beta gamma")], 14)
        self.assertEqual(
            lines[:3],
            [("assistant", "< alpha beta"), ("assistant", "  gamma"), ("assistant", "")],
        )

    def test_content_starts_after_left_rail(self) -> None:
        self.assertEqual(content_left(12), 2)
        self.assertEqual(content_left(24), 4)

    def test_colorize_wraps_text_with_ansi(self) -> None:
        self.assertEqual(colorize("hi", "user"), "\x1b[32mhi\x1b[0m")
        self.assertEqual(colorize("", "assistant"), "")

    def test_next_panel_cycles_through_views(self) -> None:
        self.assertEqual(next_panel("chat"), "models")
        self.assertEqual(next_panel("models"), "threads")
        self.assertEqual(next_panel("threads"), "chat")

    def test_panel_fetch_does_not_append_model_list_to_chat(self) -> None:
        tui = AsciiTUI(".")
        tui.panel = "models"
        tui._show_models([{"id": "gpt-test", "name": "GPT Test", "default": False}])
        self.assertEqual(len(tui.messages), 1)
        self.assertEqual(tui.models[0]["id"], "gpt-test")

    def test_model_menu_has_one_row_per_model(self) -> None:
        tui = AsciiTUI(".")
        tui._show_models([{"id": "gpt-test", "name": "GPT Test", "default": False}])
        self.assertEqual(tui._model_menu_entries(), [
            {"kind": "model", "value": "gpt-test", "label": "gpt-test"}
        ])

    def test_model_then_effort_and_atomic_submission(self) -> None:
        tui = AsciiTUI(".")
        tui.panel = "models"
        tui.models = [{"id": "gpt-test", "efforts": ["high", "xhigh"], "default_effort": "high"}]
        submitted = []
        tui.agent.command = lambda command: submitted.append(command) or True
        tui._activate_panel_selection()
        self.assertEqual(submitted, [])
        self.assertEqual(tui.panel, "models")
        self.assertEqual([e["label"] for e in tui._model_menu_entries()], ["high", "xhigh"])
        tui._key("DOWN")
        tui._activate_panel_selection()
        self.assertEqual(submitted, [Command("model_effort", "gpt-test::xhigh")])
        self.assertEqual(tui.panel, "chat")

    def test_selection_stays_visible_on_small_screen(self) -> None:
        tui = AsciiTUI(".")
        tui.panel = "models"
        tui.models = [{"id": f"model-{i}"} for i in range(40)]
        for i in range(40):
            rows = tui._body_lines(24, 4)
            self.assertLessEqual(len(rows), 4)
            self.assertIn(("assistant", f"> model-{i}"), rows)
            self.assertEqual(rows[0][1], "Choose model")
            tui._key("DOWN")
        tui._key("PGUP")
        rows = tui._body_lines(24, 4)
        self.assertIn(("assistant", f"> model-{tui.model_index}"), rows)

    def test_escape_returns_to_models_and_busy_keeps_effort_menu(self) -> None:
        tui = AsciiTUI(".")
        tui.panel = "models"
        tui.models = [{"id": "test"}]
        tui._activate_panel_selection()
        tui._key("\x1b")
        self.assertIsNone(tui.pending_model)
        tui._activate_panel_selection()
        tui.agent.command = lambda _: False
        tui._activate_panel_selection()
        self.assertIsNotNone(tui.pending_model)
        self.assertEqual(tui.panel, "models")

    def test_parse_cli_args_supports_resume_syntax(self) -> None:
        cwd, thread_id = parse_cli_args(["resume", "abc-123", "."])
        self.assertEqual(thread_id, "abc-123")
        self.assertEqual(cwd, str(Path.cwd().resolve()))

    def test_busy_submission_preserves_prompt(self) -> None:
        tui = AsciiTUI(".")
        tui.input = "a prompt to retry"
        tui.cursor = len(tui.input)
        tui.agent.ask = lambda _: False

        tui._submit()

        self.assertEqual(tui.input, "a prompt to retry")
        self.assertEqual(tui.cursor, len(tui.input))
        self.assertEqual(tui.prompt_history, [])
        self.assertEqual(tui.messages[-1].role, "error")

    def test_resume_hint_includes_command(self) -> None:
        tui = AsciiTUI(".", program_name="pcodex")
        tui.thread_id = "abc-123"
        self.assertEqual(
            tui._resume_hint(),
            "Pocket Codex closed.\nSession ID: abc-123\nResume with: pcodex resume abc-123",
        )


if __name__ == "__main__":
    unittest.main()

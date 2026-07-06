import unittest

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

    def test_model_menu_includes_effort_and_models(self) -> None:
        tui = AsciiTUI(".")
        tui._show_models([{"id": "gpt-test", "name": "GPT Test", "default": False}])
        entries = tui._model_menu_entries()
        self.assertEqual(entries[0]["kind"], "combo")
        self.assertEqual(entries[0]["value"], "gpt-test::low")
        self.assertEqual(entries[-1]["value"], "gpt-test::high")

    def test_parse_cli_args_supports_resume_syntax(self) -> None:
        cwd, thread_id = parse_cli_args(["resume", "abc-123", "."])
        self.assertEqual(thread_id, "abc-123")
        self.assertTrue(cwd.endswith("/mnt/sata/pocket-codex"))

    def test_resume_hint_includes_command(self) -> None:
        tui = AsciiTUI(".", program_name="pcodex")
        tui.thread_id = "abc-123"
        self.assertEqual(
            tui._resume_hint(),
            "Pocket Codex closed.\nSession ID: abc-123\nResume with: pcodex resume abc-123",
        )


if __name__ == "__main__":
    unittest.main()

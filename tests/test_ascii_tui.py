import unittest

from pocket_codex.ascii_tui import Message, ascii_only, wrap_messages


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


if __name__ == "__main__":
    unittest.main()

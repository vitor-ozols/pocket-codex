import unittest

from pocket_codex.render import Message, wrap_messages


class RenderTests(unittest.TestCase):
    def test_wrap_uses_role_prefix_once(self) -> None:
        lines = wrap_messages([Message("user", "one two three")], 8)
        self.assertEqual(lines[:2], [("user", "> one"), ("user", "  two")])

    def test_wrap_preserves_explicit_lines(self) -> None:
        lines = wrap_messages([Message("assistant", "a\nb")], 12)
        self.assertEqual([text for _, text in lines], ["< a", "  b", ""])


if __name__ == "__main__":
    unittest.main()

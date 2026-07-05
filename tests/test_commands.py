import unittest

from pocket_codex.commands import Command, is_known, parse_command


class CommandTests(unittest.TestCase):
    def test_plain_prompt_is_not_a_command(self) -> None:
        self.assertIsNone(parse_command("explain this"))

    def test_command_argument_is_preserved(self) -> None:
        self.assertEqual(
            parse_command("/name tiny terminal"), Command("name", "tiny terminal")
        )

    def test_alias_and_known_command(self) -> None:
        command = parse_command("/q")
        self.assertEqual(command, Command("quit"))
        self.assertTrue(is_known(command))


if __name__ == "__main__":
    unittest.main()

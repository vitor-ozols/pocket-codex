from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    name: str
    argument: str = ""


ALIASES = {
    "q": "quit",
    "exit": "quit",
    "cls": "clear",
    "abort": "stop",
}

LOCAL_COMMANDS = {"help", "clear", "quit", "stop"}
REMOTE_COMMANDS = {
    "account",
    "cd",
    "compact",
    "effort",
    "model",
    "models",
    "name",
    "new",
    "resume",
    "sandbox",
    "threads",
}

HELP = """Commands:
/new  /resume ID  /threads
/model NAME  /models
/effort low|medium|high
/sandbox read|write|full
/cd PATH  /name TEXT
/compact  /account
/stop  /clear  /quit"""


def parse_command(text: str) -> Command | None:
    if not text.startswith("/"):
        return None
    name, _, argument = text[1:].strip().partition(" ")
    name = ALIASES.get(name.lower(), name.lower())
    return Command(name=name, argument=argument.strip())


def is_known(command: Command) -> bool:
    return command.name in LOCAL_COMMANDS | REMOTE_COMMANDS


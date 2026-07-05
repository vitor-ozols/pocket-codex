from __future__ import annotations

import textwrap
from dataclasses import dataclass


@dataclass(frozen=True)
class Message:
    role: str
    text: str


PREFIXES = {
    "user": "> ",
    "assistant": "< ",
    "error": "! ",
    "info": "# ",
}


def wrap_messages(messages: list[Message], width: int) -> list[tuple[str, str]]:
    width = max(4, width)
    output: list[tuple[str, str]] = []
    for message in messages:
        prefix = PREFIXES.get(message.role, "  ")
        content_width = max(1, width - len(prefix))
        paragraphs = message.text.splitlines() or [""]
        first = True
        for paragraph in paragraphs:
            chunks = textwrap.wrap(
                paragraph,
                width=content_width,
                replace_whitespace=False,
                drop_whitespace=True,
                break_long_words=True,
                break_on_hyphens=False,
            ) or [""]
            for chunk in chunks:
                output.append((message.role, (prefix if first else "  ") + chunk))
                first = False
        output.append((message.role, ""))
    return output


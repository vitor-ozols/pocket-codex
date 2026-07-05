from __future__ import annotations

import argparse
import curses
import queue
import textwrap
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .backend import CodexWorker, Event
from .commands import Command, HELP, LOCAL_COMMANDS, is_known, parse_command


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


def ascii_only(value: Any) -> str:
    text = str(value)
    replacements = {
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2022": "*",
        "\u2026": "...",
        "\u2192": "->",
        "\u2190": "<-",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    normalized = unicodedata.normalize("NFKD", text)
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return without_accents.encode("ascii", "replace").decode()


def wrap_messages(messages: list[Message], width: int) -> list[tuple[str, str]]:
    width = max(4, width)
    output: list[tuple[str, str]] = []
    for message in messages:
        prefix = PREFIXES.get(message.role, "  ")
        content_width = max(1, width - len(prefix))
        paragraphs = ascii_only(message.text).splitlines() or [""]
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


class AsciiTUI:
    MAX_MESSAGES = 200

    def __init__(self, screen: curses.window, cwd: str) -> None:
        self.screen = screen
        self.agent = CodexWorker(cwd)
        self.messages = [Message("info", "Pocket Codex ASCII v3. /help for commands.")]
        self.input = ""
        self.cursor = 0
        self.prompt_history: list[str] = []
        self.history_index = 0
        self.scroll = 0
        self.status = "starting"
        self.thread_id = "new"
        self.running = True

    def run(self) -> None:
        self._setup()
        self.agent.start()
        try:
            while self.running:
                self._drain_events()
                self._draw()
                try:
                    key = self.screen.get_wch()
                except curses.error:
                    continue
                except KeyboardInterrupt:
                    if not self.agent.interrupt():
                        self.running = False
                    continue
                self._key(key)
        finally:
            self.agent.close()

    def _setup(self) -> None:
        curses.curs_set(1)
        self.screen.timeout(90)
        self.screen.keypad(True)
        try:
            curses.use_default_colors()
        except curses.error:
            pass

    def _drain_events(self) -> None:
        while True:
            try:
                event = self.agent.events.get_nowait()
            except queue.Empty:
                return
            self._event(event)

    def _event(self, event: Event) -> None:
        if event.kind in {"ready", "idle", "status"}:
            self.status = event.text
        elif event.kind == "answer":
            self._append("assistant", event.text)
            self.status = "ready"
            self.scroll = 0
        elif event.kind in {"error", "fatal"}:
            self._append("error", event.text)
            self.status = "error"
        elif event.kind in {"info", "config"}:
            self._append("info", event.text)
            self.scroll = 0
        elif event.kind == "thread":
            self.thread_id = event.text
            self._append("info", f"thread: {event.text}")
        elif event.kind == "models":
            self._show_models(event.data or [])
        elif event.kind == "threads":
            self._show_threads(event.data or [])
        elif event.kind == "history":
            self._load_history(event.data or {})

    def _append(self, role: str, text: str) -> None:
        self.messages.append(Message(role, text))
        if len(self.messages) > self.MAX_MESSAGES:
            del self.messages[: -self.MAX_MESSAGES]

    def _show_models(self, models: list[dict[str, Any]]) -> None:
        if not models:
            self._append("info", "No models found.")
            return
        lines = ["Models:"]
        for model in models:
            marker = "*" if model.get("default") else " "
            lines.append(f"{marker} {model['id']} - {model['name']}")
        self._append("info", "\n".join(lines))
        self.scroll = 0

    def _show_threads(self, threads: list[dict[str, str]]) -> None:
        if not threads:
            self._append("info", "No conversations found.")
            return
        lines = ["Conversations:"]
        lines.extend(f"{item['id']}  {item['name']}" for item in threads)
        self._append("info", "\n".join(lines))
        self.scroll = 0

    def _load_history(self, data: dict[str, Any]) -> None:
        restored = [
            Message(str(item["role"]), str(item["text"]))
            for item in data.get("messages", [])
        ]
        self.messages = restored or [Message("info", "This conversation is empty.")]
        self.thread_id = str(data.get("id", self.thread_id))
        self.status = "ready"
        self.scroll = 0

    def _thinking_status(self) -> str:
        if not self.agent.busy and self.status not in {"thinking", "interrupting"}:
            return self.status
        if self.status == "interrupting":
            word = "stopping"
        else:
            word = "thinking"
        dots = "." * (int(time.monotonic() * 3) % 4)
        return word + dots

    def _draw(self) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < 5 or width < 12:
            self._put(0, 0, "Terminal too small", max(1, width - 1))
            self.screen.refresh()
            return

        cwd = Path(self.agent.cwd).name or "/"
        model = self.agent.model or "default"
        header = f"[pcodex] {cwd} | {model} | {self._thinking_status()}"
        self._put(0, 0, header, width - 1, curses.A_REVERSE)

        body_height = height - 3
        lines = wrap_messages(self.messages, width - 1)
        end = max(0, len(lines) - self.scroll)
        start = max(0, end - body_height)
        for row, (role, line) in enumerate(lines[start:end], 1):
            attr = curses.A_BOLD if role in {"user", "error"} else curses.A_NORMAL
            self._put(row, 0, line, width - 1, attr)

        hint = " /help | PgUp/PgDn "
        divider_width = width - 1
        divider = ("-" * divider_width)[: max(0, divider_width - len(hint))] + hint
        self._put(height - 2, 0, divider, divider_width, curses.A_DIM)

        prompt = "> "
        available = max(1, width - len(prompt) - 1)
        visible_input = ascii_only(self.input)
        visible_cursor = len(ascii_only(self.input[: self.cursor]))
        offset = max(0, visible_cursor - available + 1)
        shown = visible_input[offset : offset + available]
        self._put(height - 1, 0, prompt + shown, width - 1)
        cursor_x = len(prompt) + visible_cursor - offset
        try:
            self.screen.move(height - 1, min(cursor_x, width - 1))
        except curses.error:
            pass
        self.screen.refresh()

    def _put(self, y: int, x: int, text: str, limit: int, attr: int = 0) -> None:
        try:
            self.screen.addnstr(y, x, ascii_only(text), max(0, limit), attr)
        except curses.error:
            pass

    def _key(self, key: int | str) -> None:
        if key in {"\n", "\r", curses.KEY_ENTER}:
            self._submit()
        elif key in {curses.KEY_BACKSPACE, 127, 8}:
            if self.cursor:
                self.input = self.input[: self.cursor - 1] + self.input[self.cursor :]
                self.cursor -= 1
        elif key == curses.KEY_DC:
            self.input = self.input[: self.cursor] + self.input[self.cursor + 1 :]
        elif key == curses.KEY_LEFT:
            self.cursor = max(0, self.cursor - 1)
        elif key == curses.KEY_RIGHT:
            self.cursor = min(len(self.input), self.cursor + 1)
        elif key == curses.KEY_HOME:
            self.cursor = 0
        elif key == curses.KEY_END:
            self.cursor = len(self.input)
        elif key == curses.KEY_UP:
            self._prompt_history(-1)
        elif key == curses.KEY_DOWN:
            self._prompt_history(1)
        elif key == curses.KEY_PPAGE:
            self.scroll += max(1, self.screen.getmaxyx()[0] - 4)
        elif key == curses.KEY_NPAGE:
            self.scroll = max(0, self.scroll - max(1, self.screen.getmaxyx()[0] - 4))
        elif key == "\x03":
            if not self.agent.interrupt():
                self.running = False
        elif key == "\x0c":
            self.messages.clear()
            self.scroll = 0
        elif key == "\x15":
            self.input = self.input[self.cursor :]
            self.cursor = 0
        elif isinstance(key, str) and key.isprintable():
            self.input = self.input[: self.cursor] + key + self.input[self.cursor :]
            self.cursor += len(key)

    def _submit(self) -> None:
        text = self.input.strip()
        if not text:
            return
        self.input = ""
        self.cursor = 0
        self.prompt_history.append(text)
        self.history_index = len(self.prompt_history)
        command = parse_command(text)
        if command:
            self._submit_command(command)
            return
        if not self.agent.ask(text):
            self._append("error", "Busy. Use /stop first.")
            return
        self._append("user", text)
        self.status = "thinking"
        self.scroll = 0

    def _submit_command(self, command: Command) -> None:
        if not is_known(command):
            self._append("error", f"Unknown command: /{command.name}")
        elif command.name == "help":
            self._append("info", HELP)
        elif command.name == "clear":
            self.messages.clear()
        elif command.name == "quit":
            self.running = False
        elif command.name == "stop":
            if not self.agent.interrupt():
                self._append("info", "No active turn.")
        elif command.name not in LOCAL_COMMANDS:
            if not self.agent.command(command):
                self._append("error", "Busy. Use /stop first.")
        self.scroll = 0

    def _prompt_history(self, delta: int) -> None:
        if not self.prompt_history:
            return
        self.history_index = min(
            len(self.prompt_history), max(0, self.history_index + delta)
        )
        self.input = (
            ""
            if self.history_index == len(self.prompt_history)
            else self.prompt_history[self.history_index]
        )
        self.cursor = len(self.input)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pocket Codex ASCII v3")
    parser.add_argument("cwd", nargs="?", default=".", help="agent working directory")
    args = parser.parse_args()
    cwd = str(Path(args.cwd).expanduser().resolve())
    if not Path(cwd).is_dir():
        parser.error(f"not a directory: {cwd}")
    curses.wrapper(lambda screen: AsciiTUI(screen, cwd).run())


if __name__ == "__main__":
    main()

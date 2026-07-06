from __future__ import annotations

import argparse
import os
import queue
import select
import shutil
import sys
import termios
import textwrap
import time
import tty
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

LEFT_PAD = 4
FRAME_PREFIX = " "
ANSI_RESET = "\x1b[0m"
ANSI_COLORS = {
    "user": "\x1b[32m",
    "assistant": "\x1b[36m",
    "error": "\x1b[31m",
    "info": "\x1b[33m",
    "header": "\x1b[37m",
    "divider": "\x1b[90m",
}
PANELS = ("chat", "models", "threads")
EFFORTS = ("low", "medium", "high")


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


def content_left(width: int) -> int:
    return min(LEFT_PAD, max(2, width // 6))


def colorize(text: str, role: str) -> str:
    color = ANSI_COLORS.get(role, "")
    if not color or not text:
        return text
    return f"{color}{text}{ANSI_RESET}"


def next_panel(panel: str) -> str:
    try:
        index = PANELS.index(panel)
    except ValueError:
        return "chat"
    return PANELS[(index + 1) % len(PANELS)]


class TerminalMode:
    def __init__(self) -> None:
        self.fd = sys.stdin.fileno()
        self._saved: list[Any] | None = None

    def __enter__(self) -> TerminalMode:
        if sys.stdin.isatty():
            self._saved = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        sys.stdout.write("\x1b[?25l\x1b[2J\x1b[H")
        sys.stdout.flush()
        return self

    def __exit__(self, *_: object) -> None:
        if self._saved is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self._saved)
        sys.stdout.write("\x1b[?25h\x1b[0m\x1b[2J\x1b[H")
        sys.stdout.flush()


class AsciiTUI:
    MAX_MESSAGES = 200

    def __init__(self, cwd: str) -> None:
        self.agent = CodexWorker(cwd)
        self.messages = [Message("info", "Pocket Codex ASCII v4. /help for commands.")]
        self.input = ""
        self.cursor = 0
        self.prompt_history: list[str] = []
        self.history_index = 0
        self.scroll = 0
        self.status = "starting"
        self.thread_id = "new"
        self.running = True
        self._buffer = ""
        self._last_frame: list[str] = []
        self._last_size = (0, 0)
        self.panel = "chat"
        self.models: list[dict[str, Any]] = []
        self.threads: list[dict[str, str]] = []
        self.model_index = 0
        self.thread_index = 0

    def run(self) -> None:
        self.agent.start()
        with TerminalMode():
            try:
                while self.running:
                    self._drain_events()
                    self._draw()
                    self._read_keys(timeout=0.09)
            finally:
                self.agent.close()

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
        self.models = models
        self.model_index = min(self.model_index, max(0, len(self._model_menu_entries()) - 1))
        if not models:
            if self.panel == "chat":
                self._append("info", "No models found.")
            return
        if self.panel != "chat":
            self.scroll = 0
            return
        lines = ["Models:"]
        for model in models:
            marker = "*" if model.get("default") else " "
            lines.append(f"{marker} {model['id']} - {model['name']}")
        self._append("info", "\n".join(lines))
        self.scroll = 0

    def _show_threads(self, threads: list[dict[str, str]]) -> None:
        self.threads = threads
        self.thread_index = min(self.thread_index, max(0, len(threads) - 1))
        if not threads:
            if self.panel == "chat":
                self._append("info", "No conversations found.")
            return
        if self.panel != "chat":
            self.scroll = 0
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
        word = "stopping" if self.status == "interrupting" else "thinking"
        dots = "." * (int(time.monotonic() * 3) % 4)
        return word + dots

    def _read_keys(self, timeout: float) -> None:
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if not ready:
            return
        chunk = os.read(sys.stdin.fileno(), 64).decode("utf-8", "ignore")
        if not chunk:
            self.running = False
            return
        self._buffer += chunk
        while True:
            key = self._pop_key()
            if key is None:
                return
            self._key(key)

    def _pop_key(self) -> str | None:
        if not self._buffer:
            return None
        if self._buffer.startswith("\x1b["):
            for seq, name in (
                ("\x1b[A", "UP"),
                ("\x1b[B", "DOWN"),
                ("\x1b[C", "RIGHT"),
                ("\x1b[D", "LEFT"),
                ("\x1b[H", "HOME"),
                ("\x1b[F", "END"),
                ("\x1b[3~", "DELETE"),
                ("\x1b[5~", "PGUP"),
                ("\x1b[6~", "PGDN"),
                ("\x1b[59;5u", "CTRL_SEMI"),
                ("\x1b[46;5u", "CTRL_DOT"),
                ("\x1b[27;5;59~", "CTRL_SEMI"),
                ("\x1b[27;5;46~", "CTRL_DOT"),
            ):
                if self._buffer.startswith(seq):
                    self._buffer = self._buffer[len(seq) :]
                    return name
            if self._buffer in {"\x1b", "\x1b["}:
                return None
            self._buffer = self._buffer[1:]
            return "ESC"
        key = self._buffer[0]
        self._buffer = self._buffer[1:]
        return key

    def _draw(self) -> None:
        width, height = shutil.get_terminal_size((80, 24))
        if height < 5 or width < 12:
            self._render_frame(["Terminal too small".ljust(max(1, width))], width, height)
            return

        left_pad = content_left(width)
        line_prefix = FRAME_PREFIX * left_pad
        content_width = max(1, width - left_pad)

        cwd = Path(self.agent.cwd).name or "/"
        model = self.agent.model or "default"
        header = f"[pcodex] {cwd} | {model} | {self._thinking_status()}"

        body_height = height - 3
        visible_lines = self._body_lines(content_width, body_height)

        frame: list[str] = [self._line(line_prefix, header, content_width, "header")]
        for role, line in visible_lines:
            frame.append(self._line(line_prefix, line, content_width, role))

        while len(frame) < height - 2:
            frame.append(self._line(line_prefix, "", content_width))

        hint = self._hint()
        divider = ("-" * content_width)[: max(0, content_width - len(hint))] + hint
        frame.append(self._line(line_prefix, divider, content_width, "divider"))
        prompt_role = "user" if self.panel == "chat" else "info"
        frame.append(self._line(line_prefix, self._prompt_line(content_width), content_width, prompt_role))

        self._render_frame(frame[:height], width, height)

    def _render_frame(self, frame: list[str], width: int, height: int) -> None:
        size = (width, height)
        output: list[str] = []
        if size != self._last_size:
            output.append("\x1b[2J")
            self._last_frame = []
            self._last_size = size

        max_rows = max(len(frame), len(self._last_frame))
        for row in range(max_rows):
            new_line = frame[row] if row < len(frame) else ""
            old_line = self._last_frame[row] if row < len(self._last_frame) else None
            if new_line == old_line:
                continue
            output.append(f"\x1b[{row + 1};1H{new_line}\x1b[K")

        if output:
            sys.stdout.write("".join(output))
            sys.stdout.flush()
        self._last_frame = list(frame)

    def _line(self, prefix: str, text: str, content_width: int, role: str = "") -> str:
        visible = ascii_only(text)[:content_width]
        return prefix + colorize(visible.ljust(content_width), role)

    def _body_lines(self, content_width: int, body_height: int) -> list[tuple[str, str]]:
        if self.panel == "models":
            lines = self._menu_lines(
                "Model + Effort",
                self._model_menu_entries(),
                self.model_index,
                lambda item: item["label"],
            )
        elif self.panel == "threads":
            lines = self._menu_lines(
                "Chat History",
                self.threads,
                self.thread_index,
                lambda item: f"{item['name']} [{item['id']}]",
            )
        else:
            lines = wrap_messages(self.messages, content_width)
        end = max(0, len(lines) - self.scroll)
        start = max(0, end - body_height)
        return lines[start:end]

    def _menu_lines(
        self,
        title: str,
        items: list[Any],
        selected: int,
        render_item: Any,
    ) -> list[tuple[str, str]]:
        lines: list[tuple[str, str]] = [("info", title), ("info", "")]
        if not items:
            lines.append(("info", "Loading..." if self.agent.busy else "No items loaded."))
            return lines
        for index, item in enumerate(items):
            marker = ">" if index == selected else " "
            role = "assistant" if index == selected else "info"
            lines.append((role, f"{marker} {render_item(item)}"))
        return lines

    def _model_menu_entries(self) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        for model in self.models:
            for effort in EFFORTS:
                selected = self.agent.model == model["id"] and self.agent.effort == effort
                entries.append(
                    {
                        "kind": "combo",
                        "value": f"{model['id']}::{effort}",
                        "label": f"{model['id']} [{effort}]{' *' if selected else ''}",
                    }
                )
        return entries

    def _hint(self) -> str:
        if self.panel == "chat":
            return " Tab panel | PgUp/PgDn | Ctrl-P/Ctrl-N "
        if self.panel == "models":
            return " Tab next | Up/Down select | Enter apply "
        return " Tab next | Up/Down select | Enter resume "

    def _prompt_line(self, content_width: int) -> str:
        if self.panel == "models":
            return "models: pick model+effort, Enter to apply"
        if self.panel == "threads":
            return "threads: select with arrows, Enter to resume"
        prompt = "> "
        available = max(1, content_width - len(prompt))
        visible_input = ascii_only(self.input)
        visible_cursor = len(ascii_only(self.input[: self.cursor]))
        offset = max(0, visible_cursor - available + 1)
        shown = visible_input[offset : offset + available]
        cursor_at = max(0, min(available - 1, visible_cursor - offset))
        if cursor_at >= len(shown):
            shown = shown + "_"
        else:
            shown = shown[:cursor_at] + "_" + shown[cursor_at + 1 :]
        return prompt + shown[:available]

    def _key(self, key: str) -> None:
        if key == "\t":
            self._cycle_panel()
        elif key in {"\n", "\r"}:
            if self.panel != "chat":
                self._activate_panel_selection()
                return
            self._submit()
        elif key in {"\x7f", "\x08"}:
            if self.panel != "chat":
                return
            if self.cursor:
                self.input = self.input[: self.cursor - 1] + self.input[self.cursor :]
                self.cursor -= 1
        elif key == "DELETE":
            if self.panel != "chat":
                return
            self.input = self.input[: self.cursor] + self.input[self.cursor + 1 :]
        elif key == "LEFT":
            if self.panel != "chat":
                return
            self.cursor = max(0, self.cursor - 1)
        elif key == "RIGHT":
            if self.panel != "chat":
                return
            self.cursor = min(len(self.input), self.cursor + 1)
        elif key == "HOME":
            if self.panel != "chat":
                return
            self.cursor = 0
        elif key == "END":
            if self.panel != "chat":
                return
            self.cursor = len(self.input)
        elif key == "UP":
            if self.panel == "models":
                self.model_index = max(0, self.model_index - 1)
            elif self.panel == "threads":
                self.thread_index = max(0, self.thread_index - 1)
            else:
                self._prompt_history(-1)
        elif key == "DOWN":
            if self.panel == "models":
                self.model_index = min(
                    max(0, len(self._model_menu_entries()) - 1),
                    self.model_index + 1,
                )
            elif self.panel == "threads":
                self.thread_index = min(max(0, len(self.threads) - 1), self.thread_index + 1)
            else:
                self._prompt_history(1)
        elif key in {"PGUP", "CTRL_SEMI", "\x10"}:
            self._scroll(1)
        elif key in {"PGDN", "CTRL_DOT", "\x0e"}:
            self._scroll(-1)
        elif key == "\x03":
            if not self.agent.interrupt():
                self.running = False
        elif key == "\x0c":
            self.messages.clear()
            self.scroll = 0
        elif key == "\x15":
            if self.panel != "chat":
                return
            self.input = self.input[self.cursor :]
            self.cursor = 0
        elif len(key) == 1 and key.isprintable():
            if self.panel != "chat":
                return
            self.input = self.input[: self.cursor] + key + self.input[self.cursor :]
            self.cursor += len(key)

    def _cycle_panel(self) -> None:
        self.panel = next_panel(self.panel)
        self.scroll = 0
        if self.panel == "models" and not self.models and not self.agent.busy:
            if not self.agent.command(Command("models")):
                self._append("error", "Busy. Use /stop first.")
        elif self.panel == "threads" and not self.threads and not self.agent.busy:
            if not self.agent.command(Command("threads")):
                self._append("error", "Busy. Use /stop first.")

    def _activate_panel_selection(self) -> None:
        if self.panel == "models":
            entries = self._model_menu_entries()
            if not entries:
                return
            entry = entries[self.model_index]
            if entry["kind"] == "combo":
                model_id, effort = entry["value"].split("::", 1)
                self._submit_command(Command("model", model_id))
                self._submit_command(Command("effort", effort))
            else:
                self._submit_command(Command(entry["kind"], entry["value"]))
            self.panel = "chat"
        elif self.panel == "threads":
            if not self.threads:
                return
            thread_id = self.threads[self.thread_index]["id"]
            self._submit_command(Command("resume", thread_id))
            self.panel = "chat"

    def _scroll(self, direction: int) -> None:
        amount = max(1, shutil.get_terminal_size((80, 24)).lines - 4)
        if direction > 0:
            self.scroll += amount
        else:
            self.scroll = max(0, self.scroll - amount)

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
    parser = argparse.ArgumentParser(description="Pocket Codex ASCII v4")
    parser.add_argument("cwd", nargs="?", default=".", help="agent working directory")
    args = parser.parse_args()
    cwd = str(Path(args.cwd).expanduser().resolve())
    if not Path(cwd).is_dir():
        parser.error(f"not a directory: {cwd}")
    AsciiTUI(cwd).run()


if __name__ == "__main__":
    main()

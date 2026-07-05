from __future__ import annotations

import argparse
import curses
import queue
from pathlib import Path

from .backend import CodexWorker, Event
from .commands import Command, HELP, LOCAL_COMMANDS, is_known, parse_command
from .render import Message, wrap_messages


class PocketTUI:
    MAX_MESSAGES = 200

    def __init__(self, screen: curses.window, cwd: str) -> None:
        self.screen = screen
        self.agent = CodexWorker(cwd)
        self.messages = [Message("info", "Pocket Codex. /help for commands.")]
        self.input = ""
        self.cursor = 0
        self.history: list[str] = []
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
        self.screen.timeout(80)
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
            self.messages.append(Message("assistant", event.text))
            self.status = "ready"
            self.scroll = 0
        elif event.kind in {"error", "fatal"}:
            self.messages.append(Message("error", event.text))
            self.status = "error"
        elif event.kind in {"info", "config"}:
            self.messages.append(Message("info", event.text))
            self.scroll = 0
        elif event.kind == "thread":
            self.thread_id = event.text
            self.messages.append(Message("info", f"thread: {event.text}"))
        if len(self.messages) > self.MAX_MESSAGES:
            del self.messages[: -self.MAX_MESSAGES]

    def _draw(self) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < 5 or width < 12:
            self._put(0, 0, "Terminal too small", max(1, width - 1))
            self.screen.refresh()
            return

        state = self.status
        if self.agent.busy and state == "ready":
            state = "thinking"
        cwd = Path(self.agent.cwd).name or "/"
        model = self.agent.model or "default"
        header = f"{cwd} | {model} | {state}"
        self._put(0, 0, header, width - 1, curses.A_REVERSE)

        body_height = height - 3
        lines = wrap_messages(self.messages, width - 1)
        end = max(0, len(lines) - self.scroll)
        start = max(0, end - body_height)
        for row, (role, line) in enumerate(lines[start:end], 1):
            attr = curses.A_BOLD if role in {"user", "error"} else curses.A_NORMAL
            self._put(row, 0, line, width - 1, attr)

        self._put(height - 2, 0, "-" * (width - 1), width - 1, curses.A_DIM)
        prompt = "> "
        available = max(1, width - len(prompt) - 1)
        offset = max(0, self.cursor - available + 1)
        shown = self.input[offset : offset + available]
        self._put(height - 1, 0, prompt + shown, width - 1)
        cursor_x = len(prompt) + self.cursor - offset
        try:
            self.screen.move(height - 1, min(cursor_x, width - 1))
        except curses.error:
            pass
        self.screen.refresh()

    def _put(self, y: int, x: int, text: str, limit: int, attr: int = 0) -> None:
        try:
            self.screen.addnstr(y, x, text, max(0, limit), attr)
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
            self._history(-1)
        elif key == curses.KEY_DOWN:
            self._history(1)
        elif key == curses.KEY_PPAGE:
            self.scroll += max(1, self.screen.getmaxyx()[0] - 4)
        elif key == curses.KEY_NPAGE:
            self.scroll = max(0, self.scroll - max(1, self.screen.getmaxyx()[0] - 4))
        elif key == "\x03":  # Ctrl-C
            if not self.agent.interrupt():
                self.running = False
        elif key == "\x0c":  # Ctrl-L
            self.messages.clear()
            self.scroll = 0
        elif key == "\x15":  # Ctrl-U
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
        self.history.append(text)
        self.history_index = len(self.history)
        command = parse_command(text)
        if command:
            self._submit_command(command)
            return
        if not self.agent.ask(text):
            self.messages.append(Message("error", "Busy. Use /stop first."))
            return
        self.messages.append(Message("user", text))
        self.status = "thinking"
        self.scroll = 0

    def _submit_command(self, command: Command) -> None:
        if not is_known(command):
            self.messages.append(Message("error", f"Unknown command: /{command.name}"))
        elif command.name == "help":
            self.messages.append(Message("info", HELP))
        elif command.name == "clear":
            self.messages.clear()
        elif command.name == "quit":
            self.running = False
        elif command.name == "stop":
            if not self.agent.interrupt():
                self.messages.append(Message("info", "No active turn."))
        elif command.name not in LOCAL_COMMANDS:
            if not self.agent.command(command):
                self.messages.append(Message("error", "Busy. Use /stop first."))
        self.scroll = 0

    def _history(self, delta: int) -> None:
        if not self.history:
            return
        self.history_index = min(
            len(self.history), max(0, self.history_index + delta)
        )
        self.input = (
            "" if self.history_index == len(self.history) else self.history[self.history_index]
        )
        self.cursor = len(self.input)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compact Codex TUI")
    parser.add_argument("cwd", nargs="?", default=".", help="agent working directory")
    args = parser.parse_args()
    cwd = str(Path(args.cwd).expanduser().resolve())
    if not Path(cwd).is_dir():
        parser.error(f"not a directory: {cwd}")
    curses.wrapper(lambda screen: PocketTUI(screen, cwd).run())


if __name__ == "__main__":
    main()

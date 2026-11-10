from __future__ import annotations

import argparse
import queue
from pathlib import Path
from typing import Any

from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, ListItem, ListView, Markdown, RichLog, Select, Static, TextArea

from .backend import CodexWorker, Event as BackendEvent
from .commands import HELP, LOCAL_COMMANDS, is_known, parse_command


class Composer(TextArea):
    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            text = self.text.strip()
            if text:
                self.post_message(self.Submitted(text))


class ConversationItem(ListItem):
    def __init__(self, thread_id: str, title: str) -> None:
        self.thread_id = thread_id
        self.title = title
        super().__init__(Static(title, markup=False))


class ChatBubble(Vertical):
    def __init__(self, role: str, text: str) -> None:
        self.role = role
        self.text = text
        label = "YOU" if role == "user" else "CODEX"
        super().__init__(
            Static(label, classes="message-label"),
            Markdown(text, open_links=True),
            classes=f"message {role}",
        )


class Thinking(Static):
    FRAMES = ("Thinking", "Thinking.", "Thinking..", "Thinking...")

    def __init__(self) -> None:
        super().__init__(self.FRAMES[0], id="thinking", classes="hidden")
        self._frame = 0

    def on_mount(self) -> None:
        self.set_interval(0.32, self._advance)

    def show(self) -> None:
        self._frame = 0
        self.update(self.FRAMES[0])
        self.remove_class("hidden")

    def hide(self) -> None:
        self.add_class("hidden")

    def _advance(self) -> None:
        if not self.has_class("hidden"):
            self._frame = (self._frame + 1) % len(self.FRAMES)
            self.update(self.FRAMES[self._frame])


class PocketCodexApp(App[None]):
    TITLE = "Pocket Codex"
    SUB_TITLE = "Compact coding agent"

    CSS = """
    Screen {
        background: #0d1715;
        color: #dce8e3;
        layers: base overlay;
    }

    #shell {
        width: 100%;
        height: 100%;
    }

    #sidebar {
        width: 32;
        height: 100%;
        background: #0a2420;
        color: #e8f1ed;
        padding: 1;
        border-right: tall #244a43;
    }

    #brand {
        height: 3;
        color: #f6c453;
        text-style: bold;
        content-align: left middle;
        padding-left: 1;
    }

    #new-chat {
        width: 100%;
        margin-bottom: 1;
        background: #e86f51;
        color: #fff8e8;
        border: none;
        text-style: bold;
    }

    .side-label {
        height: 1;
        margin: 1 1 0 1;
        color: #8dbab0;
        text-style: bold;
    }

    #model-select {
        width: 100%;
        margin-top: 1;
        background: #123d37;
        color: #edf6f2;
        border: tall #39766d;
    }

    #thread-list {
        height: 1fr;
        margin-top: 1;
        background: transparent;
        border: none;
    }

    #thread-list ListItem {
        height: auto;
        min-height: 2;
        padding: 0 1;
        margin-bottom: 1;
        color: #d8e7e1;
        background: transparent;
    }

    #thread-list ListItem:hover {
        background: #164941;
    }

    #thread-list ListItem.--highlight {
        background: #f6c453;
        color: #10231f;
        text-style: bold;
    }

    #side-hint {
        height: 2;
        color: #8dbab0;
        padding: 0 1;
    }

    #main {
        width: 1fr;
        height: 100%;
        background: #0d1715;
    }

    #topbar {
        height: 3;
        padding: 0 1;
        background: #14211f;
        border-bottom: solid #2e4540;
        align-vertical: middle;
    }

    #menu {
        width: 5;
        min-width: 5;
        height: 1;
        padding: 0;
        margin-right: 1;
        background: transparent;
        color: #9fd3c7;
        border: none;
    }

    #chat-title {
        width: 1fr;
        height: 1;
        text-style: bold;
        color: #dce8e3;
    }

    #status {
        width: auto;
        height: 1;
        color: #68b5a5;
        text-style: bold;
    }

    #chat {
        height: 1fr;
        padding: 1 2;
        scrollbar-color: #365b54;
        scrollbar-background: #0d1715;
    }

    #welcome {
        height: auto;
        padding: 2;
        margin: 1 2;
        background: #14211f;
        border: round #2e4540;
        color: #9fb7b1;
        content-align: center middle;
    }

    .message {
        width: 92%;
        height: auto;
        padding: 1 2;
        margin-bottom: 1;
        border: round #2e4540;
    }

    .message.user {
        margin-left: 4;
        background: #3d261f;
        border: round #9f513d;
    }

    .message.assistant {
        background: #14211f;
        border: round #31534c;
    }

    .message-label {
        height: 1;
        color: #68b5a5;
        text-style: bold;
    }

    .message.user .message-label {
        color: #ef967f;
    }

    .message Markdown {
        height: auto;
        background: transparent;
        color: #dce8e3;
        padding: 0;
    }

    #working-label { height: 1; color: #68b5a5; margin: 0 3; }
    #working { height: 6; margin: 0 2; background: #14211f; }

    #thinking {
        height: 2;
        margin: 0 3;
        color: #68b5a5;
        text-style: italic;
    }

    .hidden {
        display: none;
    }

    #composer-bar {
        height: 7;
        padding: 0 2 1 2;
        background: #0d1715;
        align-vertical: bottom;
    }

    #prompt {
        width: 1fr;
        height: 6;
        background: #14211f;
        color: #dce8e3;
        border: round #416e65;
        scrollbar-size: 0 0;
    }

    #prompt:focus {
        border: round #e86f51;
    }

    #send {
        width: 8;
        min-width: 8;
        height: 3;
        margin-left: 1;
        background: #123b36;
        color: #fff8e8;
        border: none;
        text-style: bold;
    }

    Screen.narrow #sidebar {
        display: none;
    }

    Screen.narrow #chat {
        padding: 0 1;
    }

    Screen.narrow .message {
        width: 100%;
        margin-left: 0;
        padding: 1;
        border: none;
    }

    Screen.narrow #composer-bar {
        padding: 0 1 1 1;
    }

    Screen.narrow.sidebar-open #sidebar {
        display: block;
        layer: overlay;
        dock: left;
        width: 85%;
        height: 100%;
        border-right: heavy #f6c453;
    }
    """

    BINDINGS = [
        Binding("ctrl+n", "new_chat", "New", show=True),
        Binding("ctrl+b", "toggle_sidebar", "History", show=True),
        Binding("tab", "switch_panel", "Panel", show=True, priority=True),
        Binding("ctrl+enter", "send", "Send", show=False),
        Binding("ctrl+c", "stop", "Stop", show=False, priority=True),
        Binding("escape", "close_sidebar", "Close", show=False),
    ]

    def __init__(self, cwd: str, worker: CodexWorker | None = None) -> None:
        super().__init__()
        self.agent = worker or CodexWorker(cwd)
        self._current_thread: str | None = None
        self._refresh_threads_on_idle = False
        self._request_threads_on_idle = False
        self._stream_messages: dict[str, ChatBubble] = {}

    def compose(self) -> ComposeResult:
        with Horizontal(id="shell"):
            with Vertical(id="sidebar"):
                yield Static("POCKET CODEX", id="brand")
                yield Button("+ New chat", id="new-chat")
                yield Static("MODEL", classes="side-label")
                yield Select([], prompt="Loading models...", id="model-select")
                yield Static("CONVERSATIONS", classes="side-label")
                yield ListView(id="thread-list")
                yield Static("Tab switch panel\nCtrl+C stop", id="side-hint")
            with Vertical(id="main"):
                with Horizontal(id="topbar"):
                    yield Button("[=]", id="menu", compact=True)
                    yield Static("New chat", id="chat-title")
                    yield Static("STARTING", id="status")
                yield VerticalScroll(
                    Static(
                        "Ask about this project. Codex can inspect files, run commands, "
                        "and make changes.",
                        id="welcome",
                    ),
                    id="chat",
                )
                yield Static("WORKING", id="working-label", classes="hidden")
                yield RichLog(id="working", max_lines=500, wrap=True, markup=False, classes="hidden")
                yield Thinking()
                with Horizontal(id="composer-bar"):
                    yield Composer(
                        soft_wrap=True,
                        show_line_numbers=False,
                        placeholder="Message Codex...",
                        id="prompt",
                    )
                    yield Button("Send", id="send")

    def on_mount(self) -> None:
        self._update_layout(self.size.width)
        self.set_interval(0.08, self._poll_backend)
        self.agent.start()
        self.query_one("#prompt", Composer).focus()

    def on_unmount(self) -> None:
        self.agent.close()

    def on_resize(self, event: events.Resize) -> None:
        self._update_layout(event.size.width)

    def _update_layout(self, width: int) -> None:
        self.screen.set_class(width < 64, "narrow")
        if width >= 64:
            self.screen.remove_class("sidebar-open")

    async def _poll_backend(self) -> None:
        for _ in range(100):
            try:
                event = self.agent.events.get_nowait()
            except queue.Empty:
                return
            await self._handle_backend_event(event)

    async def _handle_backend_event(self, event: BackendEvent) -> None:
        if event.kind == "ready":
            self._set_status("READY")
            self.agent.command(_command("models"))
        elif event.kind == "status":
            self._set_status(event.text.upper())
            if event.text in {"thinking", "interrupting"}:
                self.query_one(Thinking).show()
        elif event.kind == "idle":
            self._set_status("READY")
            self._stream_messages.clear()
            self.query_one(Thinking).hide()
            if self._refresh_threads_on_idle or self._request_threads_on_idle:
                self._refresh_threads_on_idle = False
                self._request_threads_on_idle = False
                self.agent.command(_command("threads"))
        elif event.kind in {"message_delta", "message_complete"}:
            item_id = event.data["id"]
            bubble = self._stream_messages.get(item_id)
            if bubble is None:
                bubble = await self._add_message("assistant", "")
                self._stream_messages[item_id] = bubble
            bubble.text = bubble.text + event.text if event.kind == "message_delta" else event.text
            await bubble.query_one(Markdown).update(bubble.text)
            self.query_one("#chat", VerticalScroll).scroll_end(animate=False)
        elif event.kind == "activity":
            self.query_one("#working-label").remove_class("hidden")
            log = self.query_one("#working", RichLog)
            log.remove_class("hidden")
            log.write(event.text)
        elif event.kind == "answer":
            if not (event.data or {}).get("streamed"):
                await self._add_message("assistant", event.text)
            self._refresh_threads_on_idle = True
        elif event.kind in {"error", "fatal"}:
            self.query_one(Thinking).hide()
            self._set_status("ERROR")
            self.notify(event.text, severity="error", timeout=8)
        elif event.kind == "models":
            self._load_models(event.data or [])
            self._request_threads_on_idle = True
        elif event.kind == "threads":
            await self._load_threads(event.data or [])
        elif event.kind == "history":
            await self._load_history(event.data or {})
        elif event.kind == "thread":
            self._current_thread = None if event.text == "new thread" else event.text
        elif event.kind == "config":
            self.notify(event.text, timeout=2)
        elif event.kind == "info":
            self.notify(event.text, timeout=5)

    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def _load_models(self, models: list[dict[str, Any]]) -> None:
        select = self.query_one("#model-select", Select)
        options = [(model["name"], model["id"]) for model in models]
        with select.prevent(Select.Changed):
            select.set_options(options)
        current = self.agent.model
        default = next((model["id"] for model in models if model["default"]), None)
        selected = current if current and any(
            model["id"] == current for model in models
        ) else default
        if selected:
            with select.prevent(Select.Changed):
                select.value = selected

    async def _load_threads(self, threads: list[dict[str, str]]) -> None:
        view = self.query_one("#thread-list", ListView)
        await view.clear()
        if threads:
            await view.extend(
                ConversationItem(thread["id"], thread["name"]) for thread in threads
            )

    async def _load_history(self, data: dict[str, Any]) -> None:
        await self._clear_chat()
        self._current_thread = data.get("id")
        for message in data.get("messages", []):
            await self._add_message(message["role"], message["text"], scroll=False)
        self.query_one("#chat", VerticalScroll).scroll_end(animate=False)
        self._set_status("READY")

    async def _clear_chat(self) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        self._stream_messages.clear()
        self.query_one("#working", RichLog).clear()
        self.query_one("#working").add_class("hidden")
        self.query_one("#working-label").add_class("hidden")
        await chat.remove_children()

    async def _add_message(self, role: str, text: str, *, scroll: bool = True) -> ChatBubble:
        chat = self.query_one("#chat", VerticalScroll)
        welcome = chat.query("#welcome")
        if welcome:
            await welcome.remove()
        bubble = ChatBubble(role, text)
        await chat.mount(bubble)
        if scroll:
            chat.scroll_end(animate=False)
        return bubble

    async def _send_text(self, text: str) -> bool:
        command = parse_command(text)
        if command is not None:
            await self._run_command(command)
            return True
        if not self.agent.ask(text):
            self.notify("Codex is busy. Press Ctrl+C to stop.", severity="warning")
            return False
        await self._add_message("user", text)
        self.query_one(Thinking).show()
        self._set_status("THINKING")
        return True

    async def _run_command(self, command: Any) -> None:
        if not is_known(command):
            self.notify(f"Unknown command: /{command.name}", severity="error")
        elif command.name == "help":
            self.notify(HELP, timeout=10)
        elif command.name == "clear":
            await self._clear_chat()
        elif command.name == "quit":
            self.exit()
        elif command.name == "stop":
            self.action_stop()
        elif command.name not in LOCAL_COMMANDS and not self.agent.command(command):
            self.notify("Codex is busy. Press Ctrl+C to stop.", severity="warning")

    @on(Composer.Submitted)
    async def submit_prompt(self, event: Composer.Submitted) -> None:
        composer = self.query_one("#prompt", Composer)
        composer.load_text("")
        if not await self._send_text(event.text):
            composer.load_text(event.text)

    @on(Button.Pressed, "#send")
    async def send_button(self) -> None:
        composer = self.query_one("#prompt", Composer)
        text = composer.text.strip()
        if text:
            composer.load_text("")
            if not await self._send_text(text):
                composer.load_text(text)

    @on(Button.Pressed, "#new-chat")
    async def new_chat_button(self) -> None:
        await self.action_new_chat()

    @on(Button.Pressed, "#menu")
    def menu_button(self) -> None:
        self.action_toggle_sidebar()

    @on(Select.Changed, "#model-select")
    def model_changed(self, event: Select.Changed) -> None:
        if event.value is Select.NULL:
            return
        if event.value == self.agent.model:
            return
        if not self.agent.command(_command("model", str(event.value))):
            with event.select.prevent(Select.Changed):
                event.select.value = self.agent.model or Select.NULL
            self.notify("Change the model after the current turn.", severity="warning")

    @on(ListView.Selected, "#thread-list")
    def thread_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if not isinstance(item, ConversationItem):
            return
        if not self.agent.command(_command("resume", item.thread_id)):
            self.notify("Stop the current turn before changing chats.", severity="warning")
            return
        self.query_one("#chat-title", Static).update(item.title)
        self._set_status("LOADING")
        self.action_close_sidebar()

    async def action_new_chat(self) -> None:
        if not self.agent.command(_command("new")):
            self.notify("Stop the current turn before starting a chat.", severity="warning")
            return
        self._current_thread = None
        await self._clear_chat()
        self.query_one("#chat-title", Static).update("New chat")
        self.action_close_sidebar()
        self.query_one("#prompt", Composer).focus()

    def action_toggle_sidebar(self) -> None:
        if self.screen.has_class("narrow"):
            opening = not self.screen.has_class("sidebar-open")
            self.screen.toggle_class("sidebar-open")
            if opening:
                self.query_one("#thread-list", ListView).focus()
            else:
                self.query_one("#prompt", Composer).focus()

    def action_switch_panel(self) -> None:
        if self.screen.has_class("narrow"):
            if not self.screen.has_class("sidebar-open"):
                self.screen.add_class("sidebar-open")
                self.query_one("#model-select", Select).focus()
            elif isinstance(self.focused, ListView):
                self.action_close_sidebar()
            else:
                self.screen.focus_next()
        else:
            self.screen.focus_next()

    def action_close_sidebar(self) -> None:
        self.screen.remove_class("sidebar-open")
        self.query_one("#prompt", Composer).focus()

    async def action_send(self) -> None:
        composer = self.query_one("#prompt", Composer)
        text = composer.text.strip()
        if text:
            composer.load_text("")
            await self._send_text(text)

    def action_stop(self) -> None:
        if not self.agent.interrupt():
            self.exit()


def _command(name: str, argument: str = "") -> Any:
    command = parse_command(f"/{name} {argument}".rstrip())
    assert command is not None
    return command


def main() -> None:
    parser = argparse.ArgumentParser(description="Pocket Codex Textual UI")
    parser.add_argument("cwd", nargs="?", default=".", help="agent working directory")
    args = parser.parse_args()
    cwd = str(Path(args.cwd).expanduser().resolve())
    if not Path(cwd).is_dir():
        parser.error(f"not a directory: {cwd}")
    PocketCodexApp(cwd).run()


if __name__ == "__main__":
    main()

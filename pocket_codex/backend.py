from __future__ import annotations

import os
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .commands import Command


@dataclass(frozen=True)
class Event:
    kind: str
    text: str = ""


class CodexWorker:
    """Owns the SDK client in one worker thread and exposes a small event queue."""

    def __init__(self, cwd: str) -> None:
        self.cwd = str(Path(cwd).expanduser().resolve())
        self.model: str | None = None
        self.effort = "medium"
        self.sandbox_name = "write"
        self.events: queue.Queue[Event] = queue.Queue()
        self._jobs: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._thread: Any = None
        self._active_turn: Any = None
        self._busy = threading.Event()
        self._closed = threading.Event()
        self._worker = threading.Thread(target=self._run, daemon=True)

    @property
    def busy(self) -> bool:
        return self._busy.is_set()

    def start(self) -> None:
        self._worker.start()

    def ask(self, prompt: str) -> bool:
        if self.busy:
            return False
        self._jobs.put(("ask", prompt))
        return True

    def command(self, command: Command) -> bool:
        if self.busy:
            return False
        self._jobs.put(("command", command))
        return True

    def interrupt(self) -> bool:
        turn = self._active_turn
        if turn is None:
            return False

        def do_interrupt() -> None:
            try:
                turn.interrupt()
            except Exception as exc:  # SDK errors must not break the UI thread.
                self.events.put(Event("error", f"Interrupt failed: {exc}"))

        threading.Thread(target=do_interrupt, daemon=True).start()
        self.events.put(Event("status", "interrupting"))
        return True

    def close(self) -> None:
        self._closed.set()
        if self.busy:
            self.interrupt()
        self._jobs.put(("close", None))
        self._worker.join(timeout=3)

    def _run(self) -> None:
        try:
            from openai_codex import Codex, Sandbox
        except ImportError:
            self.events.put(
                Event("fatal", "Missing SDK. Run: pip install openai-codex")
            )
            return

        self._sandbox = {
            "read": Sandbox.read_only,
            "write": Sandbox.workspace_write,
            "full": Sandbox.full_access,
        }

        try:
            with Codex() as client:
                self._client = client
                self.events.put(Event("ready", "ready"))
                while not self._closed.is_set():
                    job, payload = self._jobs.get()
                    if job == "close":
                        break
                    self._busy.set()
                    try:
                        if job == "ask":
                            self._ask(payload)
                        else:
                            self._command(payload)
                    except Exception as exc:
                        self.events.put(Event("error", str(exc)))
                    finally:
                        self._active_turn = None
                        self._busy.clear()
                        self.events.put(Event("idle", "ready"))
        except Exception as exc:
            self.events.put(Event("fatal", f"Codex failed to start: {exc}"))

    def _ensure_thread(self) -> Any:
        if self._thread is None:
            kwargs = {
                "cwd": self.cwd,
                "sandbox": self._sandbox[self.sandbox_name],
            }
            if self.model:
                kwargs["model"] = self.model
            self._thread = self._client.thread_start(**kwargs)
            self.events.put(Event("thread", str(self._thread.id)))
        return self._thread

    def _ask(self, prompt: str) -> None:
        thread = self._ensure_thread()
        self.events.put(Event("status", "thinking"))
        kwargs: dict[str, Any] = {
            "cwd": self.cwd,
            "effort": self.effort,
            "sandbox": self._sandbox[self.sandbox_name],
        }
        if self.model:
            kwargs["model"] = self.model
        self._active_turn = thread.turn(prompt, **kwargs)
        result = self._active_turn.run()
        if result.final_response:
            self.events.put(Event("answer", result.final_response))
        elif result.error:
            self.events.put(Event("error", str(result.error)))
        else:
            self.events.put(Event("status", f"turn ended: {result.status}"))

    def _command(self, command: Command) -> None:
        handler = getattr(self, f"_cmd_{command.name}", None)
        if handler is None:
            self.events.put(Event("error", f"Unknown command: /{command.name}"))
            return
        handler(command.argument)

    def _cmd_new(self, _: str) -> None:
        self._thread = None
        self.events.put(Event("thread", "new thread"))

    def _cmd_resume(self, thread_id: str) -> None:
        if not thread_id:
            raise ValueError("Usage: /resume THREAD_ID")
        kwargs = {
            "cwd": self.cwd,
            "sandbox": self._sandbox[self.sandbox_name],
        }
        if self.model:
            kwargs["model"] = self.model
        self._thread = self._client.thread_resume(thread_id, **kwargs)
        self.events.put(Event("thread", str(self._thread.id)))

    def _cmd_threads(self, _: str) -> None:
        response = self._client.thread_list(cwd=self.cwd, limit=12)
        rows = _items(response, "data", "threads", "items")
        if not rows:
            self.events.put(Event("info", "No threads found."))
            return
        lines = []
        for row in rows:
            thread_id = str(_value(row, "id", "thread_id", default="?"))
            name = str(_value(row, "name", "title", "preview", default=""))
            lines.append(f"{thread_id} {name}".rstrip())
        self.events.put(Event("info", "\n".join(lines)))

    def _cmd_name(self, name: str) -> None:
        if not name:
            raise ValueError("Usage: /name TEXT")
        self._ensure_thread().set_name(name)
        self.events.put(Event("info", f"Thread named: {name}"))

    def _cmd_compact(self, _: str) -> None:
        self._ensure_thread().compact()
        self.events.put(Event("info", "Thread compacted."))

    def _cmd_model(self, model: str) -> None:
        if not model:
            self.events.put(Event("info", self.model or "model: Codex default"))
            return
        self.model = model
        self.events.put(Event("config", f"model={model}"))

    def _cmd_models(self, _: str) -> None:
        response = self._client.models()
        rows = _items(response, "data", "models", "items")
        names = [str(_value(row, "id", "model", "slug", default=row)) for row in rows]
        self.events.put(Event("info", "\n".join(names) or "No models returned."))

    def _cmd_effort(self, effort: str) -> None:
        if effort not in {"low", "medium", "high"}:
            raise ValueError("Usage: /effort low|medium|high")
        self.effort = effort
        self.events.put(Event("config", f"effort={effort}"))

    def _cmd_sandbox(self, name: str) -> None:
        if name not in self._sandbox:
            raise ValueError("Usage: /sandbox read|write|full")
        self.sandbox_name = name
        self.events.put(Event("config", f"sandbox={name}"))

    def _cmd_cd(self, path: str) -> None:
        if not path:
            self.events.put(Event("info", self.cwd))
            return
        target = Path(os.path.expandvars(path)).expanduser().resolve()
        if not target.is_dir():
            raise ValueError(f"Not a directory: {target}")
        self.cwd = str(target)
        self.events.put(Event("config", f"cwd={self.cwd}"))

    def _cmd_account(self, _: str) -> None:
        response = self._client.account()
        account = _value(response, "account", default=response)
        account = _value(account, "root", default=account)
        email = _value(account, "email", "name", "id", default=account)
        self.events.put(Event("info", f"account: {email}"))


def _value(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(obj, dict) and name in obj:
            value = obj[name]
            if value is not None:
                return value
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


def _items(obj: Any, *names: str) -> list[Any]:
    if isinstance(obj, list):
        return obj
    value = _value(obj, *names, default=[])
    return list(value or [])

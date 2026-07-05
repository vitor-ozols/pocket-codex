# Pocket Codex

Responsive Codex chat for terminals, including 240x320 displays. It keeps the
agent capabilities in the official Python SDK while showing only prompts, final
answers, errors, and a compact animated activity indicator.

The Textual interface includes Markdown messages, a model picker, persistent
Codex conversation history, and a responsive sidebar. On narrow terminals the
sidebar becomes a drawer so the chat keeps the full display width.

## Install

Python 3.10 or newer and an existing Codex login are required.

```bash
cd /mnt/sata/pocket-codex
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
pocket-codex /path/to/project
```

The SDK reuses the current Codex authentication. To authenticate separately,
run `codex login` before starting Pocket Codex.

## Keys

- `Enter`: send; `Shift-Enter` inserts a line break
- `Ctrl-Enter`: send
- `Ctrl-N`: new conversation
- `Ctrl-B`: show or hide conversation history
- `Tab`: switch between chat and sidebar on narrow screens
- `Ctrl-C`: interrupt the active turn; quit when idle
- `Escape`: close the history drawer

## Commands

```text
/help                    compact help
/new                     start a new thread
/resume THREAD_ID        resume a Codex thread
/threads                 list recent threads
/name TEXT               name the current thread
/compact                 compact the current thread
/model [MODEL]           show or select a model
/models                   list available models
/effort low|medium|high  reasoning effort
/sandbox read|write|full workspace access
/cd PATH                 change the agent working directory
/account                  show the active account
/stop                     interrupt the active turn
/clear                    clear the screen
/quit                     exit
```

The sidebar model picker changes the model used by subsequent turns. Pocket
Codex defaults to `workspace_write` and `medium` reasoning effort. The SDK is
currently beta, so its public API can change before version 1.0.

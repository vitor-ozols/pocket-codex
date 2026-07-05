# Pocket Codex

Minimal Codex TUI for small terminals, including 240x320 displays. It keeps the
agent capabilities in the official Python SDK while showing only prompts, final
answers, errors, and a compact activity indicator.

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

- `Enter`: send
- `Ctrl-C`: interrupt the active turn; quit when idle
- `Ctrl-L`: clear the visible conversation
- `Page Up` / `Page Down`: scroll
- `Up` / `Down`: prompt history

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

Pocket Codex defaults to `workspace_write`, leaves model selection to the Codex
configuration, and uses `medium` reasoning effort. The SDK is currently beta,
so its public API can change before version 1.0.


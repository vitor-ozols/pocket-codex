# Pocket Codex

Compact Codex clients for terminals, including 240x320 displays. Both clients
use the official Python SDK. The Textual client streams assistant messages and
shows command output, file changes, and tool activity in a bounded Working panel.
Both clients stream assistant text and show tool activity. The ASCII client pins
recent activity below the chat; `Ctrl-W` opens its scrollable Working log.
Reasoning logs stay hidden.

## Interfaces

The default v3 is a full-ASCII `curses` interface designed for small or limited
terminals:

```bash
pocket-codex /path/to/project
# Same interface under an explicit name:
pocket-codex-ascii /path/to/project
```

The previous Textual interface remains available with Markdown, a model picker,
and a conversation sidebar:

```bash
pocket-codex-textual /path/to/project
```

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

## ASCII keys

- `Enter`: send
- `Ctrl-C`: interrupt the active turn; quit when idle
- `Ctrl-W`: open or close the Working log (use `Page Up` / `Page Down` to scroll)
- `Ctrl-L`: clear visible messages
- `Ctrl-U`: clear input before the cursor
- `Tab`: switch panels
- Models: choose a model with arrows and `Enter`, then choose its effort and `Enter`
- `Escape`: return from effort selection to models
- `Up` / `Down`: prompt history, or selection in menus (scroll follows selection)
- `Page Up` / `Page Down`: scroll

## Textual keys

- `Enter`: send; `Shift-Enter` inserts a line break
- `Ctrl-Enter`: send
- `Ctrl-N`: new conversation
- `Ctrl-B`: show or hide conversation history
- `Tab`: open the model picker on narrow screens, then move through sidebar controls
- Model picker: `Enter` to open, arrow keys to choose, `Enter` to confirm
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

The Textual sidebar model picker and the ASCII `/model` command change the model
used by subsequent turns. Pocket Codex defaults to `workspace_write` and
`medium` reasoning effort. The SDK is currently beta, so its public API can
change before version 1.0.

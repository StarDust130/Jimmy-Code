<div align="center">

# 🕺 Jimmy Code

### A terminal-native AI coding agent that can **think, act, test, and ship.**

<img src="/public/jimmy.gif" alt="Jimmy Code"/>

**Jimmy Jimmy Ajaa 🎶**

`task → think → code → test → ship`

<br/>

**🍳 Give Jimmy a task. Let Jimmy cook.**

<br/>

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square\&logo=python\&logoColor=white)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-290%2B%20passing-22c55e?style=flat-square\&logo=pytest\&logoColor=white)]()
[![Textual](https://img.shields.io/badge/UI-Textual-8b5cf6?style=flat-square)](https://textual.textualize.io/)
[![LiteLLM](https://img.shields.io/badge/LLM-LiteLLM-f59e0b?style=flat-square)](https://docs.litellm.ai/)
[![SQLite](https://img.shields.io/badge/storage-SQLite%20WAL-003B57?style=flat-square\&logo=sqlite\&logoColor=white)](https://sqlite.org/)
[![License](https://img.shields.io/badge/license-MIT-a855f7?style=flat-square)](LICENSE)

</div>

---

## ✨ What is Jimmy?

**Jimmy Code is a terminal-native AI coding agent built with Python and Textual.**

Give Jimmy a coding task and it can inspect your project, read and edit files, run commands and tests, work with Git, and iterate on the result through an agent loop.

Everything happens inside your terminal.

No browser dashboard.
No Electron app.
Just your terminal, your codebase, and Jimmy.

```text
You
 ↓
Task
 ↓
Jimmy thinks
 ↓
Tools execute
 ↓
Results are observed
 ↓
Jimmy continues / fixes / tests
 ↓
Done
```

---

## 🎬 Jimmy in Action

The interface is built around a live activity timeline so you can see what Jimmy is actually doing.

```text
❯ commit that all 4 with short fun emoji message

⠹ checking git status···  0.3s

✓ checking git status  8ms

✓ reading jimmy.tcss · 128 lines · 4.1k chars  90ms

✓ committing "styling widgets nicely 🍜"  9ms

✓ committing "formatting table rows 🗃"  24ms

I have committed all 4 files individually…

✦ 9.5s · 9.8k in · 393 out · 9 tools · 4 rounds · ⧉ copy
```

Tool activity is treated as a **timeline**, not a wall of logs.

Running actions stay visible.
Completed actions become quieter.
Useful information stays easy to scan.

---

## 🚀 Features

### 🤖 Real agent loop

Jimmy doesn't just generate code.

It can:

```text
think → call tools → observe results → continue → correct → test
```

It supports streamed LLM responses, asynchronous tool execution, self-correction, and configurable step budgets.

### 🧰 Coding tools

Jimmy currently ships with focused tools for:

```text
📖 read_files
🔍 search_files
✏️ edit_files
💻 shell
📂 list_files
📝 write_file
🩹 apply_patch
🧪 run_tests
🌿 git
```

### 🛡️ Permission system

Choose how much control Jimmy has.

| Mode               | Shell | Git Push | Edit Files | Read |
| ------------------ | :---: | :------: | :--------: | :--: |
| 🟢 **Ask**         |   ✋   |     ✋    |      ✋     |   ✓  |
| 🟡 **Auto**        |   ✋   |     ✋    |      ✓     |   ✓  |
| 🔴 **Full Access** |   ✓   |     ✓    |      ✓     |   ✓  |

When approval is required, Jimmy shows the action before executing it.

```text
🛡️ Approval required

Jimmy wants to:
run `git push origin main`

why:
this action executes commands or can be destructive

✅ Allow
🔓 Allow session
❌ Deny
```

Permission changes are always explicit and fail closed.

### 🗄️ Persistent sessions

Sessions are stored locally using **SQLite + WAL**.

Jimmy remembers:

* conversations
* tool calls
* tool results
* errors
* session metadata

Sessions can be resumed after restarting Jimmy.

Storage:

```text
~/.jimmy/sessions.db
```

### 🤖 Multiple models

Jimmy uses **LiteLLM** for model/provider support.

Features include:

* dynamic provider/model discovery
* searchable model picker
* unavailable/deprecated model filtering
* runtime model switching
* conversation history preservation
* persistent model configuration

Configuration:

```text
~/.jimmy/models.json
```

### 🎨 Terminal-first UI

Jimmy is designed as an actual terminal application rather than a CLI wrapped around an AI API.

The UI includes:

* live tool timeline
* interactive approval screens
* model picker
* session browser
* command palette
* themes
* sound
* keyboard-first navigation
* copyable results

---

## ⚡ Install

### Recommended

```bash
git clone https://github.com/StarDust130/Jimmy-Code.git
cd Jimmy-Code
uv sync
```

### Or with pip

```bash
git clone https://github.com/StarDust130/Jimmy-Code.git
cd Jimmy-Code
pip install -e .
```

### Requirements

* Python **3.12+**
* A terminal
* API key for at least one supported model provider

---

## 🏃 Quick Start

Launch Jimmy:

```bash
jimmy
```

Or start with a task:

```bash
jimmy "fix the failing tests in src/"
```

### Configure a model

Press:

```text
Ctrl+M
```

Choose your provider and model, then add your API key.

You can also use:

```text
/model
```

Your model configuration is saved locally.

---

## ⌨️ Keyboard Shortcuts

| Key      | Action           | Key      | Action          |
| -------- | ---------------- | -------- | --------------- |
| `Enter`  | Send             | `Ctrl+P` | Command palette |
| `Esc`    | Interrupt / Back | `Ctrl+M` | Model picker    |
| `/`      | Slash commands   | `Ctrl+O` | Sessions        |
| `↑ ↓`    | History / Menu   | `Ctrl+C` | Copy last       |
| `Ctrl+N` | Home             | `Ctrl+A` | Copy all        |
| `Ctrl+L` | Clear line       | `Ctrl+S` | Sound           |
| `Ctrl+H` | Home             | `Ctrl+Q` | Quit            |

---

## 🍜 Slash Commands

| Command        | Action                     |
| -------------- | -------------------------- |
| `/model`       | Open model picker          |
| `/permissions` | Change permission mode     |
| `/sessions`    | Browse and resume sessions |
| `/new`         | Start a new session        |
| `/theme`       | Change theme               |
| `/sound`       | Play / stop sound          |
| `/clear`       | Clear the chat             |
| `/copy`        | Copy last exchange         |
| `/copyall`     | Copy everything            |
| `/help`        | Show help                  |
| `/quit`        | Exit Jimmy                 |

---

## 🏗️ Architecture

```text
                         ┌──────────────────────┐
                         │      JimmyApp        │
                         │      Textual TUI     │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │      Agent Loop      │
                         │  think ⇄ tool ⇄ obs  │
                         └──────────┬───────────┘
                                    │
                 ┌──────────────────┼──────────────────┐
                 │                  │                  │
                 ▼                  ▼                  ▼
        ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
        │  Permissions   │ │ Tool Registry  │ │    LiteLLM     │
        │     Policy     │ │   9 tools      │ │    Providers   │
        └────────────────┘ └────────────────┘ └────────────────┘
                 │                  │                  │
                 └──────────────────┼──────────────────┘
                                    ▼
                         ┌──────────────────────┐
                         │ SQLite Session Store │
                         │       + WAL          │
                         └──────────────────────┘
```

Core boundaries:

```text
UI ≠ agent
policy ≠ tools
tools ≠ storage
```

The TUI handles presentation and interaction while the agent, permission system, tools, and session layer remain separated.

---

## 📁 Project Structure

```text
src/
├── jimmy/
│   ├── agent/          # agent loop + events
│   ├── context/        # token pruning + clipping
│   ├── llm/            # providers, models, config, cost
│   ├── permissions/    # policy + approval system
│   ├── sessions/       # SQLite store + recorder
│   ├── tools/          # tool registry + built-ins
│   └── workspace/      # project scope
│
└── tui/
    ├── app.py          # JimmyApp
    ├── kit/            # themes, sound, helpers, assets
    ├── screens/        # home, models, sessions, permissions
    └── widgets/        # chat, composer, rows, top bar
```

---

## 🧪 Testing

Run the test suite:

```bash
uv run pytest -q
```

Current suite:

```text
290+ tests
```

Tests cover the agent loop, permission system, approval flows, SQLite migrations, session recovery, cleanup policies, UI flows, and keyboard interactions.

---

## 🗺️ Roadmap

### Done

* [x] 🛡️ Permission system
* [x] 🗄️ Persistent SQLite sessions
* [x] 🏷️ Automatic session titles
* [x] 🤖 Multi-model support
* [x] 🔁 Runtime model switching
* [x] 🧰 Coding tool suite
* [x] 🎨 Terminal UI

### Next

* [ ] 🔎 Long-term memory
* [ ] 🖼️ Image / file attachments
* [ ] 🧩 MCP tool plugins

---

## 🥚 Jimmy Has Opinions

<details>
<summary>Click for questionable wisdom</summary>

```text
$ jimmy "why am I single?"

Because even your git history
has no meaningful commits. 💀
```

</details>

---

<div align="center">

### 🍳 Give Jimmy a task. Let Jimmy cook.

**Made for the terminal. Built with chaos. 👀**

`task → think → code → test → ship`

</div>

# 🧠 Jimmy — Code Agent V1 Roadmap

> **Jimmy is a lightweight coding agent that turns a task into a tested solution.**
> Inspect the codebase → think → use tools → test → done. ✅

---

## 🚀 V1 Roadmap

| Status | # | Milestone | Goal |
|:---:|:---:|---|---|
| ✅ | **01** | 📂 **Project Setup** | `pyproject.toml`, dependencies, configuration |
| ✅ | **02** | 🐍 **CLI** | `jimmy "fix this bug"` |
| ✅ | **03** | 🤖 **LLM Provider** | OpenAI, DeepSeek, Gemini, Groq |
| ⭕ | **04** | 🔧 **Tool System** | Tool interface + registry |
| ⭕ | **05** | 🔍 **Search + Read** | Explore and inspect the codebase |
| ⭕ | **06** | ✏️ **Edit** | Safely modify files |
| ⭕ | **07** | 💻 **Shell / Test** | Run commands and tests |
| ⭕ | **08** | 🔄 **Agent Loop** ⭐ | LLM → Tool → Result → LLM |
| ⭕ | **09** | 🧠 **State** | Remember the current task |
| ⭕ | **10** | 🛡️ **Safety** | Permissions, limits, timeouts |
| ⭕ | **11** | 🧪 **Real Testing** | Solve real-world bugs |
| ⭕ | **12** | ✨ **CLI Polish** | Streaming, errors, Ctrl-C |

**Legend:** `✅ Done` · `⭕ Up next`

## 🗺️ The Journey

```text
📂 Project Setup
       │
       ▼
🐍 CLI
       │
       ▼
🤖 LLM Provider
       │
       ▼
🔧 Tool System
       │
       ▼
🔍 Search + Read Tools
       │
       ▼
✏️ Edit Tool
       │
       ▼
💻 Shell / Test Tool
       │
       ▼
🔄 Agent Loop
       │
       ▼
🧠 State + Conversation
       │
       ▼
🛡️ Safety + Limits
       │
       ▼
🧪 Real Testing
       │
       ▼
✨ CLI Polish
       │
       ▼
🎉 Jimmy V1 Finished
```

---

## ⚙️ Core Agent Loop

The heart of Jimmy is the agent loop:

```text
┌──────────┐
│   User   │
│  Task    │
└────┬─────┘
     │
     ▼
┌──────────┐
│   LLM    │
│  Think   │
└────┬─────┘
     │
     ▼
┌──────────┐
│   Tool   │
│  Execute │
└────┬─────┘
     │
     ▼
┌──────────┐
│  Result  │
└────┬─────┘
     │
     └───────────► back to LLM
                     │
                     ▼
                   Done ✅
```

### 🔁 The loop

```text
LLM
 ↓
Choose tool
 ↓
Execute tool
 ↓
Observe result
 ↓
Think again
 ↓
Choose next tool
 ↓
...
 ↓
Finish
```

---

## 🎯 The Goal

> ### `task → inspect → think → tools → test → done`

Jimmy shouldn't just **generate code**.

It should:

**understand → investigate → act → verify**

---

## 🧩 What V1 Unlocks

By the end of V1, Jimmy should be able to take something like:

```bash
jimmy "fix the failing authentication test"
```

and autonomously:

```text
🔍 Inspect repository
      ↓
🧠 Understand the failure
      ↓
📖 Read relevant files
      ↓
✏️ Modify the code
      ↓
🧪 Run tests
      ↓
🔄 Iterate if needed
      ↓
✅ Confirm the fix
```

---

## 🛡️ V1 Principles

Jimmy should be:

* **Simple** — small, understandable architecture
* **Composable** — tools and providers are easy to add
* **Safe** — controlled permissions and execution limits
* **Observable** — clear output and useful errors
* **Testable** — real repositories, real bugs, real verification

---

## 🏁 Definition of Done

Jimmy V1 is finished when it can reliably:

```text
✅ Accept a coding task from the CLI
✅ Understand an unfamiliar codebase
✅ Search and read files
✅ Edit files safely
✅ Run shell commands and tests
✅ Iterate using an agent loop
✅ Keep task state
✅ Handle failures and timeouts
✅ Respect safety limits
✅ Solve real coding bugs
✅ Present the process cleanly in the CLI
```

---

## ⭐ Jimmy V1

```text
        ┌──────────────────────┐
        │        JIMMY         │
        │     CODE AGENT       │
        └──────────┬───────────┘
                   │
                   ▼
             Give it a task
                   │
                   ▼
              🔍 Inspect
                   │
                   ▼
               🧠 Think
                   │
                   ▼
              🔧 Use tools
                   │
                   ▼
               🧪 Test
                   │
                   ▼
                ✅ Done
```

> **From a plain-English task to a verified code change.**
>
> **That is Jimmy V1.** 🚀

# 🧠 Jimmy — Coding Agent

> **Jimmy turns a plain-English task into a tested code change.**
>
> `inspect → think → act → test → done` ✅

---

## 🗺️ Roadmap

### 🏁 V1 — Foundation ✅🎉

<details>
<summary><strong>🎉 View V1 milestones</strong></summary>

|Status     |    #   | Milestone            | Goal                                           |
| :-: | :----: | -------------------- | ---------------------------------------------- |
|  ✅  | **01** | 📂 **Project Setup** | `pyproject.toml`, dependencies & configuration |
|  ✅  | **02** | 🐍 **CLI**           | `jimmy "fix this bug"`                         |
|  ✅  | **03** | 🤖 **LLM Providers** | OpenAI, DeepSeek, Gemini & Groq                |
|  ✅  | **04** | 🔧 **Tool System**   | Tool interface + registry                      |
|  ✅  | **05** | 🔍 **Search + Read** | Explore and inspect the codebase               |
|  ✅  | **06** | ✏️ **Edit**          | Safely modify files                            |
|  ✅  | **07** | 💻 **Shell / Test**  | Run commands and tests                         |
|  ✅  | **08** | 🔄 **Agent Loop** ⭐  | LLM → Tool → Result → LLM                      |
|  ✅  | **09** | 🧠 **State**         | Remember the current task                      |
|  ✅  | **10** | 🛡️ **Safety**       | Permissions, limits & timeouts                 |
|  ✅  | **11** | 🧪 **Real Testing**  | Solve real-world bugs                          |
|  ✅  | **12** | ✨ **CLI Polish**     | Streaming, errors & Ctrl-C                     |

</details>

**V1 status: `12 / 12` complete ✅**

---

### 🚀 V2 — Intelligence & Scale



<details open>
<summary><strong>🚧 View V2 milestones</strong></summary>

|Status     |    #   | Milestone                       | What it unlocks                              |
| :-: | :----: | ------------------------------- | -------------------------------------------- |
|  ✅  | **01** | 🧠 **Agent Architecture**       | Planning, execution, observation & recovery  |
|  ✅  | **02** | 📋 **Planning System**          | Create and track real task plans             |
|  ✅  | **03** | 🧭 **Codebase Exploration**     | Understand project structure before editing  |
|  ✅  | **04** | 🛠️ **Tool System V2**          | Schemas, validation, results & metadata      |
|  ✅  | **05** | ✂️ **Context Management**       | Compression, summarization & context budgets |
|  ✅  | **06** | 🔄 **Recovery + Retry**         | Recover from failed tools, tests & edits     |
|  ✅  | **07** | 🧪 **Test → Fix → Retest**      | Autonomous debugging loops                   |
|  ⭕  | **08** | 🌳 **Git Intelligence**         | Status, diff, branches, commits & rollback   |
|  ⭕  | **09** | 🔐 **Permission System**        | Approve dangerous actions                    |
|  ⭕  | **10** | 💾 **Session Persistence**      | Resume interrupted sessions                  |
|  ⭕  | **11** | ⚡ **Parallel Execution**        | Run independent tools concurrently           |
|  ⭕  | **12** | 📊 **Observability**            | Logs, traces, tokens, latency & cost         |
|  ⭕  | **13** | 💰 **Cost + Budgets**           | Control task & model spending                |
|  ⭕  | **14** | 🤖 **Multi-Provider LLM**       | Cloud + local model support                  |
|  ⭕  | **15** | 🧩 **Model Routing**            | Pick the right model per task                |
|  ⭕  | **16** | 🧠 **Coding Intelligence**      | Symbols, language-aware search & discovery   |
|  ⭕  | **17** | 🔌 **MCP Support**              | Connect external tools & services            |
|  ⭕  | **18** | 🪝 **Hooks System**             | Tool, session & lifecycle hooks              |
|  ⭕  | **19** | 🧱 **Workspace Isolation**      | Worktrees + optional sandbox                 |
|  ⭕  | **20** | 🔍 **Diff Review**              | Review changes before finishing              |
|  ⭕  | **21** | 🧑‍⚖️ **Reviewer Agent**        | Independent implementation review            |
|  ⭕  | **22** | 🔁 **Revision Loop**            | Review → fix → review                        |
|  ⭕  | **23** | 🧪 **Evaluation Harness**       | Benchmark repeatable coding tasks            |
|  ⭕  | **24** | 📈 **Agent Metrics**            | Pass rate, cost/task & failure reasons       |
|  ⭕  | **25** | 🖥️ **TUI V2**                  | Plans, tools, diffs & progress               |
|  ⭕  | **26** | ⚙️ **Configuration**            | Project, model & tool settings               |
|  ⭕  | **27** | 🧰 **Plugin Architecture**      | Add tools without changing core              |
|  ⭕  | **28** | 📦 **Packaging + Distribution** | Install Jimmy with one command               |
|  ⭕  | **29** | 🛡️ **Production Hardening**    | Reliability, security & concurrency          |
|  ⭕  | **30** | 🏁 **V2 Release**               | Stable production-style coding agent         |

</details>

🧭 V2 at a Glance

- 🧠 01–07 — Agent Intelligence
- 🛡️ 08–13 — Reliability & Control
- 🤖 14–16 — Model Intelligence
- 🧩 17–22 — Extensibility & Multi-Agent
- 📊 23–30 — Evaluation & Productization

**V2 status: `7 / 30` complete 🚧**
---

🎍 Extra 
- Add agent Skills (e.g., `jimmy skills list`) to show what Jimmy can do


---

## 🧭 V2 Principles

V2 is not just about adding more features.
It is about making Jimmy **more capable without becoming unpredictable.**

| Principle                     | What it means                                       |
| ----------------------------- | --------------------------------------------------- |
| 🧠 **Reason Before Acting**   | Build a plan before making complex changes          |
| 🔄 **Recover, Don't Restart** | Failures should trigger recovery and retry          |
| 🧪 **Verify Everything**      | Changes should be tested and reviewed               |
| 🛡️ **Safety First**          | Dangerous actions require explicit control          |
| 👀 **Stay Observable**        | Users should understand what Jimmy is doing         |
| 💰 **Respect Budgets**        | Control tokens, models, time and cost               |
| 🧩 **Composable by Design**   | Tools, models and plugins should remain replaceable |
| 📦 **Isolate Work**           | Keep agent changes safe and reversible              |
| ⚡ **Scale Intelligently**     | Parallelize work when it is safe and useful         |
| 🎯 **Optimize for Outcomes**  | Measure success by verified task completion         |

> **V1:** Build the foundation. ✅
> **V2:** Make the foundation intelligent. 🚀

---

## 🏗️ Architecture

V1 established the basic loop. V2 expands it into a more capable runtime:

```text
                         👤 User
                           │
                           ▼
                      🖥️ TUI / CLI
                           │
                           ▼
                    🧠 Agent Runtime
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
           📋 Plan      🧠 State     💰 Budget
              └────────────┼────────────┘
                           ▼
                    🤖 Model Router
                           │
               ┌───────────┼───────────┐
               ▼           ▼           ▼
            OpenAI      Gemini      DeepSeek
               │
               ▼
             🔄 PLAN → ACT → OBSERVE
                    ↑          │
                    └─ RECOVER ┘
                           │
                           ▼
                    🔧 Tool Runtime
                           │
                ┌──────────┼──────────┐
                ▼          ▼          ▼
             🔍 Search   ✏️ Edit   💻 Shell
                └──────────┼──────────┘
                           ▼
                       🛡️ Policy
                           │
                           ▼
                     🌳 Workspace
                      ┌────┴────┐
                      ▼         ▼
                   Git Repo   Sandbox
                      │
                      ▼
                  🔍 Reviewer
                      │
                      ▼
                   ✅ Result
```

---

## 🔄 Core Agent Loop

```text
Task
 ↓
Plan
 ↓
Act
 ↓
Observe
 ↓
Recover if needed
 ↓
Verify
 ↓
Done ✅
```

The V1 loop was:

> `LLM → Tool → Result → LLM`

V2 evolves it into:

> `PLAN → ACT → OBSERVE → RECOVER → VERIFY`

---

## 🎯 What Jimmy Is Becoming

Give Jimmy a task:

```bash
jimmy "fix the failing authentication test"
```

The long-term goal is:

```text
🔍 Understand the repository
        ↓
📋 Build a plan
        ↓
🧠 Select the right model
        ↓
🔧 Execute tools
        ↓
🧪 Run tests
        ↓
🔄 Recover from failures
        ↓
🔍 Review the changes
        ↓
✅ Deliver a verified result
```

---

## 🧩 What V1 Proved

V1 established that Jimmy can:

```text
✅ Accept real coding tasks
✅ Explore unfamiliar repositories
✅ Read and modify files
✅ Execute shell commands
✅ Run tests
✅ Maintain task state
✅ Iterate through an agent loop
✅ Respect safety limits
✅ Solve real coding bugs
```

**V1 is done.**
Now the focus shifts from **making Jimmy work** to **making Jimmy work reliably at scale**.

---

## ⭐ The Jimmy Vision

```text
        ┌─────────────────────┐
        │        JIMMY        │
        │    CODE AGENT 🧠    │
        └──────────┬──────────┘
                   │
                   ▼
              Give it a task
                   │
                   ▼
                🔍 Inspect
                   │
                   ▼
                📋 Plan
                   │
                   ▼
                🧠 Reason
                   │
                   ▼
              🔧 Use tools
                   │
                   ▼
                 🧪 Test
                   │
                   ▼
                🔍 Review
                   │
                   ▼
                 ✅ Done
```

> **From a plain-English task to a verified code change.**
>
> **V1 built Jimmy. V2 teaches Jimmy how to work.** 🚀

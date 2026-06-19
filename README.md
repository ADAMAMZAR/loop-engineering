# Agent From Scratch

A learning project: build a tiny coding agent — harness and loop included —
from a single API call up to something that can autonomously work a real
GitHub repo. Each phase is a standalone, runnable script that builds on the
last.

## Project structure

| File | Phase | What it does |
|---|---|---|
| [`single_tool_call.py`](single_tool_call.py) | 0 | One raw tool-use request/response — no loop. |
| [`agent_loop.py`](agent_loop.py) | 1 | Wires the call into a ReAct loop with four tools. |
| [`safe_harness.py`](safe_harness.py) | 2 | Adds approval gating, a path sandbox, and an audit log. |
| [`ralph_loop.py`](ralph_loop.py) | 3 | Autonomously works through `spec.md`, one fresh instance per task. |
| [`spec.md`](spec.md) | 3 | Task checklist `ralph_loop.py` reads from and checks off. |
| `sample.txt` | — | Fixture file the agent reads during demos. |

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install openai python-dotenv
```

Create a `.env` file in the project root:

```
GOOGLE_API_KEY=your_key_here
```

Get a key from [aistudio.google.com](https://aistudio.google.com). DeepSeek
is supported too — each script has a commented-out DeepSeek client block;
uncomment it and set `DEEPSEEK_API_KEY` instead if you want to switch
providers.

## Roadmap

- [x] **Phase 0 — One agent call** (`single_tool_call.py`)
  See the raw tool-use request/response. No loop yet — just the seam.

- [x] **Phase 1 — The basic agentic loop** (`agent_loop.py`)
  Wire the call into a loop: send → tool_use → you execute it → feed the
  result back → repeat until the model stops asking for tools. Tools:
  `read_file`, `write_file`, `list_dir`, `run_shell`. This is the ReAct
  pattern every coding agent runs underneath.

- [x] **Phase 2 — Harness: make it safe** (`safe_harness.py`)
  Wraps the loop from Phase 1 with:
  - a permission system (read-only tools auto-run, mutating tools need your
    approval first)
  - a sandbox (file tools are restricted to the project directory;
    `run_shell` runs with `cwd` pinned there, though the approval gate is
    the real safety net for that tool)
  - an audit log (every tool call and decision written to `audit_log.jsonl`,
    one JSON line each, replayable)

- [x] **Phase 3 — Loop engineering: make it autonomous** (`ralph_loop.py`)
  Ralph pattern: the agent reads `spec.md`, picks the first unchecked
  item, implements it with a fresh, memory-free conversation, verifies its
  own work, checks the item off, and commits — then the next task gets its
  own fresh instance with zero memory of the last one. State lives in
  `spec.md` and the git log, not in any conversation. No approval gate
  here (that's the point of "autonomous"); capped at 5 tasks per run as a
  safety stop.

- [ ] **Phase 4 — Point it at something real**
  Run it against a real repo with a narrow goal and the Phase 2 approval
  gate active before anything gets pushed.

## Phase 0 — what to look for when you run it

Run `python single_tool_call.py` and read the printed output. You should
see a tool-call block, not an answer about what's in the file. That's the
whole point: the model asked you to read the file, it didn't read it
itself. `finish_reason` will be `"tool_calls"` — that value is what every
loop checks to decide "do I need to act before I can continue?"

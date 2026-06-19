# Agent From Scratch

A learning project: build a tiny coding agent — harness and loop included —
from a single API call up to something that can autonomously work a real
GitHub repo. Each phase is a runnable script that builds on the last.

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install openai python-dotenv
# Create a .env file with:
# GOOGLE_API_KEY=your_key_here   (from aistudio.google.com)
# DeepSeek is supported too (see the commented-out client block in each
# script) — set DEEPSEEK_API_KEY instead if you switch back.
```

## Roadmap

- [x] **Phase 0 — One agent call** (`phase0_single_call.py`)
  See the raw tool-use request/response. No loop yet — just the seam.

- [x] **Phase 1 — The basic agentic loop** (`phase1_loop.py`)
  Wire the call into a loop: send → tool_use → you execute it → feed the
  result back → repeat until the model stops asking for tools. Tools: `read_file`,
  `write_file`, `list_dir`, `run_shell`. This is the ReAct pattern every coding
  agent runs underneath.

- [x] **Phase 2 — Harness: make it safe** (`phase2_harness.py`)
  Wraps the loop from Phase 1 with:
  - a permission system (read-only tools auto-run, mutating tools need your
    approval first)
  - a sandbox (file tools are restricted to the project directory; `run_shell`
    runs with `cwd` pinned there, though the approval gate is the real
    safety net for that tool)
  - an audit log (every tool call and decision written to `phase2_audit.log`,
    one JSON line each, replayable)

- [ ] **Phase 3 — Loop engineering: make it autonomous**
  Ralph pattern: the agent reads a `spec.md` of tasks, picks one unchecked
  item, implements it, runs tests, checks it off, commits — then a *fresh*
  instance with a clean context starts the next one. Teaches stateless,
  externally-persisted loop design and stopping conditions.

- [ ] **Phase 4 — Point it at something real**
  Run it against a real repo (e.g. devtasks) with a narrow goal and the
  Phase 2 approval gate active before anything gets pushed.

## Phase 0 — what to look for when you run it

Run `python phase0_single_call.py` and read the printed output. You should
see a `tool_use` block, not an answer about what's in the file. That's the
whole point: Claude asked you to read the file, it didn't read it itself.
`stop_reason` will be `"tool_use"` — that value is what every loop checks to
decide "do I need to act before I can continue?"

When you're ready, say the word and we'll build Phase 1.

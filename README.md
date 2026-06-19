# Agent From Scratch

[![Tests](https://github.com/ADAMAMZAR/loop-engineering/actions/workflows/tests.yml/badge.svg)](https://github.com/ADAMAMZAR/loop-engineering/actions/workflows/tests.yml)

A learning project: build a tiny coding agent — harness and loop included —
from a single API call up to something that can autonomously work a real
GitHub repo. Each phase is a standalone, runnable script that builds on the
last.

## Project structure

| File | Phase | What it does |
|---|---|---|
| [`single_tool_call.py`](single_tool_call.py) | 0 | One raw tool-use request/response — no loop. |
| [`agent_loop.py`](agent_loop.py) | 1 | Wires the call into a ReAct loop with four tools. |
| [`safe_harness.py`](safe_harness.py) | 2 | Adds approval gating, a path sandbox, a `run_shell` command allowlist, and an audit log. |
| [`ralph_loop.py`](ralph_loop.py) | 3 | Autonomously works through `spec.md`, one fresh instance per task. |
| [`spec.md`](spec.md) | 3 | Task checklist `ralph_loop.py` reads from and checks off. |
| [`test_ralph_verification.py`](test_ralph_verification.py) | 3 | Unit tests for the verification gate and retry logic. |
| [`test_run_shell_sandbox.py`](test_run_shell_sandbox.py) | 2 | Unit tests for the `run_shell` allowlist/sandbox. |
| [`audit_replay.py`](audit_replay.py) | 2 | Query/pretty-print any audit log JSONL file (`python audit_replay.py audit_log.jsonl --tool write_file`, or `agent-audit audit_log.jsonl --tool write_file`). |
| [`test_audit_replay.py`](test_audit_replay.py) | 2 | Unit tests for `audit_replay.py`'s filtering and formatting. |
| [`real_repo_loop.py`](real_repo_loop.py) | 4 | Single narrow goal against this real repo, approval-gated, with a stricter second gate before `git push`. |
| [`test_cli_args.py`](test_cli_args.py) | — | Unit tests for each script's CLI argument parsing. |
| [`test_api_error_handling.py`](test_api_error_handling.py) | — | Unit tests for the missing-API-key check and the wrapped chat-completion call. |
| [`requirements.txt`](requirements.txt) | — | Pinned dependency versions. |
| [`pyproject.toml`](pyproject.toml) | — | Makes the project pip-installable and registers the `agent-harness`/`agent-ralph`/`agent-real-repo`/`agent-audit` console commands. |
| [`.github/workflows/tests.yml`](.github/workflows/tests.yml) | — | CI: runs the full test suite on every push/PR. |
| [`agent_secrets.py`](agent_secrets.py) | — | Resolves the API key from `GOOGLE_API_KEY` or, failing that, a file named by `GOOGLE_API_KEY_FILE`. |
| [`test_agent_secrets.py`](test_agent_secrets.py) | — | Unit tests for `agent_secrets.py`. |
| [`agent_logging.py`](agent_logging.py) | — | Shared `logging` setup (level controlled by `LOG_LEVEL`) used by the three runnable scripts. |
| [`test_agent_logging.py`](test_agent_logging.py) | — | Unit tests for `agent_logging.py`. |
| [`agent_shell.py`](agent_shell.py) | 2 | Shared `run_shell`: binary allowlist plus a git/pip subcommand allowlist, used by all three runnable scripts. |
| [`test_agent_shell.py`](test_agent_shell.py) | 2 | Unit tests for the subcommand allowlist, including the per-script git push policy. |
| `sample.txt` | — | Fixture file the agent reads during demos. |

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -e .
```

This installs the project itself (via `pyproject.toml`), not just its
dependencies, and registers four console commands you can run from anywhere
— `agent-harness`, `agent-ralph`, `agent-real-repo`, `agent-audit` — instead
of needing to `cd` into this directory and run `python some_script.py`. They
each accept the same arguments as their `python <script>.py` equivalent
below (e.g. `agent-harness "fix the bug in parser.py"`,
`agent-ralph --spec other_tasks.md`). If you'd rather not install the
package, `pip install -r requirements.txt` plus `python <script>.py` still
works exactly as before.

Create a `.env` file in the project root:

```
GOOGLE_API_KEY=your_key_here
```

Get a key from [aistudio.google.com](https://aistudio.google.com). DeepSeek
is supported too — each script has a commented-out DeepSeek client block;
uncomment it and set `DEEPSEEK_API_KEY` instead if you want to switch
providers. This has actually been tested against the real API, not just
assumed: a live request with that `base_url`/model combination authenticated
and reached the model correctly, failing only on account balance (HTTP 402),
not on auth or an unrecognized model — so the integration itself is
confirmed correct, even though a full successful response wasn't observed.

If `GOOGLE_API_KEY` isn't set, every script checks for it before making any
API call and exits with a clear error message instead of failing deep inside
an HTTP request. Similarly, if the chat-completion call itself fails
(network blip, bad key, rate limit), it's caught and reported as a normal
stopping condition rather than an unhandled stack trace — `ralph_loop.py`
treats it like a run-wide failure (not retried, since the next call would
likely fail the same way) and `safe_harness.py`/`real_repo_loop.py` stop the
loop cleanly. Covered by `test_api_error_handling.py`.

If you'd rather not put the key in a plain `.env` file — e.g. you're running
in Docker or Kubernetes and prefer the "secret as a mounted file" pattern
those platforms favor over env vars — set `GOOGLE_API_KEY_FILE` to a file
path instead, and `agent_secrets.py` reads the key from there. `GOOGLE_API_KEY`
takes priority if both are set. Covered by `test_agent_secrets.py`.

## Logging

All three runnable scripts (`safe_harness.py`, `ralph_loop.py`,
`real_repo_loop.py`) log their status — tool execution, verification
results, retries, non-convergence, errors — through Python's `logging`
module instead of bare `print()`, configured by `agent_logging.py`. Logs go
to stderr with a timestamp and level, so stdout stays free for the model's
own output and any interactive approval prompts. Set `LOG_LEVEL` (e.g.
`LOG_LEVEL=DEBUG`) to control verbosity; it defaults to `INFO`. Covered by
`test_agent_logging.py`.

## The run_shell allowlist

`agent_shell.py` is the shared `run_shell` implementation for all three
runnable scripts. Beyond restricting which binaries can run at all (`git`,
`python`, `pip`, `pytest`), it also restricts *which subcommands* of `git`
and `pip` are allowed — being an allowed binary doesn't mean every
subcommand it exposes is safe to let an agent run unreviewed:

- `git` is restricted to `status`, `diff`, `log`, `show`, `add`, `commit` by
  default. Notably excluded: `push`, `config`, `remote`, `clone`, `fetch`,
  `pull`, `checkout`, `reset`. `real_repo_loop.py` is the one exception —
  it adds `push` back, since that script's whole job is `git add` / `commit`
  / `push` and the push is already gated separately by
  `request_push_approval`. `safe_harness.py` and, especially, `ralph_loop.py`
  (which has no approval gate at all) never get `push`.
- `pip` is restricted to `list`, `show`, `freeze`, `check` everywhere —
  `install`/`uninstall`/`download` are blocked on all three scripts, since
  an agent installing arbitrary packages on its own is a supply-chain risk
  regardless of which script is running it. Dependencies belong in
  `requirements.txt`, reviewed by a human.

This is **not** a full sandbox. `python -c "<anything>"` is a complete
scripting environment, and no allowlist over argv can constrain what code
it runs — that would need real OS-level isolation (a container, VM, or
seccomp profile), which is out of scope for this project. What this
allowlist narrows is the *shell command* surface, not arbitrary code run by
an interpreter that's itself allowed to execute. Covered by
`test_agent_shell.py`.

## Tests

```bash
python -m unittest test_ralph_verification test_run_shell_sandbox test_audit_replay test_cli_args test_api_error_handling test_agent_secrets test_agent_logging test_agent_shell
```

None of these tests make a real API call or need `GOOGLE_API_KEY` set — every
OpenAI response is mocked. A GitHub Actions workflow
(`.github/workflows/tests.yml`) runs this same command on every push and pull
request against Python 3.11 and 3.13, so a regression gets caught by CI
before it gets caught by you running the script live.

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
  - a sandbox: file tools are restricted to the project directory, and
    `run_shell` (shared across all three runnable scripts via
    `agent_shell.py`) parses its command into argv and runs it with
    `shell=False` against a fixed binary allowlist (`git`, `python`, `pip`,
    `pytest`) — with no real shell present, `&&`, `;`, `|`, backticks, and
    redirection have nothing to interpret them, so they end up as inert
    literal arguments instead of chained commands. On top of that, `git`
    and `pip` each get a subcommand-level allowlist too (see
    [The run_shell allowlist](#the-run_shell-allowlist) below), since being
    an allowed binary doesn't mean every subcommand it exposes is safe to
    run unreviewed. Covered by `test_run_shell_sandbox.py` and
    `test_agent_shell.py`.
  - a blast-radius cap: the main loop is bounded at `MAX_ITERATIONS`
    iterations and `MAX_TOKENS_PER_RUN` tokens, so a model that keeps
    requesting tools forever can't loop — or spend — without limit, even
    if every individual tool call gets approved.
  - an audit log that's actually queryable: every tool call and decision
    is written to `audit_log.jsonl`, one JSON line each, and
    `audit_replay.py` reads any of this project's JSONL audit logs and
    filters by tool, decision, task text, or timestamp range, instead of
    the log existing only to be read by eye. Covered by
    `test_audit_replay.py`.

  Run it with `python safe_harness.py "your goal here"` (or, if you ran
  `pip install -e .`, just `agent-harness "your goal here"`) — the goal is
  a CLI argument, not something you edit into the script. Omit it to run
  the built-in demo task.

- [x] **Phase 3 — Loop engineering: make it autonomous** (`ralph_loop.py`)
  Ralph pattern: the agent reads `spec.md`, picks the first unchecked
  item, implements it with a fresh, memory-free conversation, and checks
  the item off and commits — then the next task gets its own fresh
  instance with zero memory of the last one. State lives in `spec.md` and
  the git log, not in any conversation. No approval gate here (that's the
  point of "autonomous"); capped at 5 tasks per run as a safety stop.

  Tasks can carry a `- verify: \`command\`` line. After the agent finishes,
  the harness itself — not the agent — runs that command and only checks
  the box and commits if it exits 0. This replaced trusting the model's
  own "I tested it, it works" claim, after a live Phase 4 run proved that
  claim can be wrong (see Phase 4 below).

  If verification fails, the task gets exactly one retry: a brand-new
  fresh instance (still memory-free of other tasks) is told what the
  verification command reported and asked to fix it. If that second
  attempt also fails, the run stops there for a human to look at, rather
  than auto-retrying forever on a broken task.

  Each task's own tool-calling loop is also bounded independently of the
  per-run task cap: it gives up early as "stuck" if the same tool call
  produces the same result several times in a row, and as
  "max_iterations" if it just never finishes in `MAX_ITERATIONS_PER_TASK`
  calls. Either case counts as a failed attempt and feeds the same
  one-retry path above, instead of silently burning the whole task budget
  on a loop that was never going to converge.

  A `MAX_TOKENS_PER_RUN` budget is also tracked across the *entire run*
  (every task, every attempt, every iteration). If a run goes over it,
  `run_task` stops immediately rather than making another API call, and
  that failure is never retried — retrying would just spend more of a
  budget that's already gone.

  Before a run starts, it also scans `spec.md` for any pending task with
  no verify command and prints them up front, so a gap in the spec is
  visible before the run begins rather than discovered task-by-task once
  it's already underway. Covered by `test_ralph_verification.py`.

  Run it with `python ralph_loop.py` (or `agent-ralph`), or point it at a
  different task file with `python ralph_loop.py --spec other_tasks.md`
  (or `agent-ralph --spec other_tasks.md`) — no code editing needed to
  change which checklist it works through.

- [x] **Phase 4 — Point it at something real** (`real_repo_loop.py`)
  A single narrow goal (add a LICENSE file) run against this actual repo,
  with the Phase 2 mutating-tool approval gate active, plus a second,
  stricter gate specifically for `git push`: it shows the real outgoing
  diff (`git diff --stat origin/main..HEAD`) and requires typing the exact
  word `PUSH` to confirm — generic `y` isn't enough for the one action
  that's hard to take back.

  Run it with `python real_repo_loop.py "your goal here"` (or
  `agent-real-repo "your goal here"`). Omit the goal to run the built-in
  MIT-license demo goal.

## Phase 0 — what to look for when you run it

Run `python single_tool_call.py` and read the printed output. You should
see a tool-call block, not an answer about what's in the file. That's the
whole point: the model asked you to read the file, it didn't read it
itself. `finish_reason` will be `"tool_calls"` — that value is what every
loop checks to decide "do I need to act before I can continue?"

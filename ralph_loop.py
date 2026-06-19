import os
import re
import json
import shlex
import subprocess
import datetime
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# --- DeepSeek (commented out) ---
# client = OpenAI(
#     base_url="https://api.deepseek.com",
#     api_key=os.environ.get("DEEPSEEK_API_KEY")
# )
# MODEL = "deepseek-chat"

# --- Google AI Studio (Gemini), via its OpenAI-compatible endpoint ---
client = OpenAI(
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    api_key=os.environ.get("GOOGLE_API_KEY")
)
MODEL = "gemini-2.5-flash"

WORKDIR = os.path.abspath(os.path.dirname(__file__))
SPEC_PATH = os.path.join(WORKDIR, "spec.md")
AUDIT_LOG_PATH = os.path.join(WORKDIR, "ralph_audit.jsonl")

# Safety cap: a buggy spec or a model that never finishes a task shouldn't
# be able to loop forever or commit unboundedly in one run.
MAX_TASKS_PER_RUN = 5

# No approval gate here, unlike safe_harness.py — full autonomy is the
# point of the Ralph pattern. That tradeoff is why Phase 4 (real repos)
# brings the approval gate back.

tools = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a text file from disk.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file to read."}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write text content to a file on disk, overwriting it if it exists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file to write."},
                    "content": {"type": "string", "description": "Text content to write to the file."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List the files and folders in a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the directory. Defaults to the current directory."}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run a shell command and return its stdout, stderr, and exit code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to execute."}
                },
                "required": ["command"],
            },
        },
    },
]


def resolve_in_sandbox(path):
    resolved = os.path.abspath(os.path.join(WORKDIR, path))
    if resolved != WORKDIR and not resolved.startswith(WORKDIR + os.sep):
        raise PermissionError(f"'{path}' resolves outside the sandbox ({WORKDIR})")
    return resolved


def read_file(path):
    with open(resolve_in_sandbox(path), "r", encoding="utf-8") as f:
        return f.read()


def write_file(path, content):
    with open(resolve_in_sandbox(path), "w", encoding="utf-8") as f:
        f.write(content)
    return f"Wrote {len(content)} characters to {path}"


def list_dir(path="."):
    return "\n".join(os.listdir(resolve_in_sandbox(path)))


# The fixed set of binaries the agent's run_shell tool may invoke. This is
# the tool the autonomous agent calls itself; run_verification below is a
# separate, harness-controlled path and is intentionally not restricted
# the same way, since the harness writes that command, not the agent.
ALLOWED_SHELL_COMMANDS = {"git", "python", "pip", "pytest"}


def run_shell(command):
    """Parse into argv and execute directly (shell=False), restricted to
    ALLOWED_SHELL_COMMANDS — see safe_harness.py's run_shell for why this
    replaces a plain shell=True call.
    """
    try:
        args = shlex.split(command)
    except ValueError as e:
        return f"Error: could not parse command: {e}"
    if not args:
        return "Error: empty command."

    binary = os.path.basename(args[0]).lower()
    if binary.endswith(".exe"):
        binary = binary[:-4]
    if binary not in ALLOWED_SHELL_COMMANDS:
        return (
            f"Error: '{binary}' is not in the allowed command list "
            f"{sorted(ALLOWED_SHELL_COMMANDS)}. Rejected before execution."
        )

    result = subprocess.run(args, shell=False, cwd=WORKDIR, capture_output=True, text=True, timeout=30)
    return f"exit code: {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"


TOOL_FUNCTIONS = {
    "read_file": read_file,
    "write_file": write_file,
    "list_dir": list_dir,
    "run_shell": run_shell,
}


def log_event(event):
    event["timestamp"] = datetime.datetime.now().isoformat()
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def execute_tool_call(tool_call):
    name = tool_call.function.name
    args = json.loads(tool_call.function.arguments)
    print(f"\n--- executing tool: {name}({args}) ---")
    try:
        result = TOOL_FUNCTIONS[name](**args)
    except Exception as e:
        result = f"Error: {e}"
    log_event({"tool": name, "args": args, "result": str(result)[:500]})
    print(f"--- result: {result} ---")
    return str(result)


# Safety stops for a single task's own tool-calling loop, independent of
# MAX_TASKS_PER_RUN (which bounds how many *tasks* one run attempts). These
# bound how much one *task* can spin before something is clearly wrong.
MAX_ITERATIONS_PER_TASK = 15
STUCK_REPEAT_THRESHOLD = 3

# Token budget across the *entire run* — all tasks, all attempts, all
# iterations. This is the outermost blast-radius limit: even if every task
# and retry stays within its own cap, a run that's just doing a lot of
# legitimate work could still spend more than intended. This is checked
# and accumulated globally rather than per-task because the budget is
# meant to bound one invocation of this script, not one task within it.
MAX_TOKENS_PER_RUN = 100_000
total_tokens_used = 0


def record_usage(response):
    """Add this response's token usage to the run-wide total. Returns True
    once the run-wide budget has been exceeded.
    """
    global total_tokens_used
    usage = getattr(response, "usage", None)
    tokens = getattr(usage, "total_tokens", 0) if usage else 0
    total_tokens_used += tokens
    return total_tokens_used > MAX_TOKENS_PER_RUN


def run_task(task_text, retry_context=None):
    """One fresh, stateless agent instance implementing a single spec task.

    A brand-new `messages` list means this conversation has no memory of
    any other task the loop has run — the only things that persist across
    tasks are spec.md (which task is checked off) and the git log (what
    actually got committed). That's the externally-persisted state the
    Ralph pattern relies on instead of a long-lived conversation.

    `retry_context`, when set, is the failure detail (verification output,
    or a non-convergence reason) from a previous attempt at this same
    task. The new instance still starts with zero memory of *other*
    tasks — it just gets told why the last attempt at *this* task didn't
    pass, so a retry isn't a blind repeat.

    Returns (outcome, detail):
      - ("completed", message_content) — the model stopped requesting tools.
      - ("stuck", reason) — the same tool call produced the same result
        STUCK_REPEAT_THRESHOLD times in a row; continuing would just burn
        more calls on a loop that isn't going anywhere.
      - ("max_iterations", reason) — hit MAX_ITERATIONS_PER_TASK without
        finishing, e.g. a task that's too large or too ambiguous for one
        pass.
      - ("budget_exceeded", reason) — the run-wide token budget
        (MAX_TOKENS_PER_RUN) has been used up. Unlike the other two
        outcomes, the caller should not retry this — retrying would just
        spend more of a budget that's already gone.
    """
    prompt = (
        f"Implement this task from spec.md: {task_text}\n\n"
        "Use the available tools to read/write files and run shell "
        "commands as needed. Verify your work by running it before "
        "you finish."
    )
    if retry_context:
        prompt += (
            "\n\nA previous attempt at this exact task did not succeed. "
            f"Here is what happened:\n{retry_context}\n\n"
            "Diagnose and fix the underlying issue, then try again."
        )
    messages = [{"role": "user", "content": prompt}]
    recent_calls = []

    for _ in range(MAX_ITERATIONS_PER_TASK):
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=1024,
            tools=tools,
            messages=messages,
        )

        if record_usage(response):
            reason = (
                f"Run-wide token budget exceeded ({total_tokens_used}/"
                f"{MAX_TOKENS_PER_RUN} tokens used). Stopping before any more API calls."
            )
            print(f"\n=== TOKEN BUDGET EXCEEDED ===\n{reason}")
            return "budget_exceeded", reason

        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        if message.content:
            print(f"\n--- assistant says ---\n{message.content}")

        if not message.tool_calls:
            return "completed", message.content

        for tool_call in message.tool_calls:
            result = execute_tool_call(tool_call)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                }
            )

            recent_calls.append((tool_call.function.name, tool_call.function.arguments, result))
            if (
                len(recent_calls) >= STUCK_REPEAT_THRESHOLD
                and len(set(recent_calls[-STUCK_REPEAT_THRESHOLD:])) == 1
            ):
                reason = (
                    f"Stuck: {tool_call.function.name} was called with the same "
                    f"arguments and produced the same result {STUCK_REPEAT_THRESHOLD} "
                    f"times in a row. Last result:\n{result}"
                )
                print(f"\n=== NON-CONVERGENCE DETECTED ===\n{reason}")
                return "stuck", reason

    reason = f"Hit the {MAX_ITERATIONS_PER_TASK}-iteration cap without finishing this task."
    print(f"\n=== NON-CONVERGENCE DETECTED ===\n{reason}")
    return "max_iterations", reason


TASK_LINE_RE = re.compile(r"^- \[( |x)\] (.+)$")
VERIFY_LINE_RE = re.compile(r"^\s*- verify: `(.+)`$")


def parse_tasks(lines):
    r"""Pure parsing logic, split out from file I/O so it's unit-testable.

    A task may be followed by a `  - verify: \`command\`` line. That command
    is run by the harness itself (not the agent) after the task finishes,
    and is the actual gate for checking the box and committing — the
    model's own claim that it "verified" its work is not trusted.
    """
    tasks = []
    current = None
    for i, line in enumerate(lines):
        stripped = line.rstrip("\n")
        match = TASK_LINE_RE.match(stripped)
        if match:
            if current is not None:
                tasks.append(current)
            current = {
                "line_index": i,
                "done": match.group(1) == "x",
                "text": match.group(2),
                "verify": None,
            }
            continue
        if current is not None:
            vmatch = VERIFY_LINE_RE.match(stripped)
            if vmatch:
                current["verify"] = vmatch.group(1)
    if current is not None:
        tasks.append(current)
    return tasks


def load_tasks():
    with open(SPEC_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return lines, parse_tasks(lines)


def mark_task_done(lines, line_index):
    lines[line_index] = lines[line_index].replace("- [ ]", "- [x]", 1)
    with open(SPEC_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)


def commit_task(task_text):
    subprocess.run(["git", "add", "-A"], cwd=WORKDIR, check=True)
    subprocess.run(["git", "commit", "-m", f"Ralph: {task_text}"], cwd=WORKDIR, check=True)


def run_verification(command):
    """Run the task's verify command for real and judge it by exit code.

    This is the harness checking the work, not the agent self-reporting on
    it — the distinction that was missing before (the Phase 4 LICENSE run
    reported success while the content was actually wrong).
    """
    result = subprocess.run(
        command, shell=True, cwd=WORKDIR, capture_output=True, text=True, timeout=30
    )
    output = f"exit code: {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return result.returncode == 0, output


def handle_task_completion(task):
    """Decide whether a finished task gets checked off and committed.

    Returns (True, None) if it was (verification passed, or no verify
    command was defined for the task). Returns (False, output) if
    verification ran and failed — `output` is the verification command's
    report, which the caller can feed back into a retry.
    """
    if task["verify"]:
        passed, output = run_verification(task["verify"])
        log_event(
            {
                "task": task["text"],
                "verify_command": task["verify"],
                "verify_passed": passed,
                "verify_output": output[:1000],
            }
        )
        if not passed:
            print(f"\n=== VERIFICATION FAILED for task: {task['text']} ===")
            print(output)
            return False, output
        print(f"=== Verification passed: {task['verify']} ===")
    else:
        print("=== WARNING: task has no verify command; checking off on trust ===")

    lines, tasks_now = load_tasks()
    fresh_task = next(t for t in tasks_now if t["line_index"] == task["line_index"])
    mark_task_done(lines, fresh_task["line_index"])
    commit_task(task["text"])
    return True, None


# A task gets one fresh instance, and if verification fails, one more fresh
# instance told exactly why the first one failed. Past that, it's a human's
# problem, not the loop's — unbounded auto-retry on the same broken task is
# how a buggy spec turns into a runaway loop.
MAX_ATTEMPTS_PER_TASK = 2


def run_task_with_retries(task):
    """Run a task, retrying once with failure context if verification fails.

    Returns True if the task ended up checked off and committed, False if
    every attempt was exhausted and the run should stop for human review.
    """
    retry_context = None
    for attempt in range(1, MAX_ATTEMPTS_PER_TASK + 1):
        print(
            f"\n=== Fresh instance starting task (attempt {attempt}/"
            f"{MAX_ATTEMPTS_PER_TASK}): {task['text']} ==="
        )
        outcome, detail = run_task(task["text"], retry_context)

        if outcome == "budget_exceeded":
            log_event(
                {"task": task["text"], "non_convergence": outcome, "detail": str(detail)[:1000]}
            )
            print(f"=== Stopping entire run, not just this task: {detail} ===")
            return False

        if outcome != "completed":
            log_event(
                {"task": task["text"], "non_convergence": outcome, "detail": str(detail)[:1000]}
            )
            if attempt < MAX_ATTEMPTS_PER_TASK:
                retry_context = detail
                print("=== Retrying with a fresh instance, given the failure above ===")
                continue
            print(
                f"=== Giving up on task after {MAX_ATTEMPTS_PER_TASK} attempts "
                f"(last failure: {outcome}): {task['text']} — stopping run for human review ==="
            )
            return False

        success, output = handle_task_completion(task)
        if success:
            print(f"=== Checked off and committed: {task['text']} ===")
            return True
        if attempt < MAX_ATTEMPTS_PER_TASK:
            retry_context = output or "Previous attempt did not finish successfully."
            print("=== Retrying with a fresh instance, given the failure above ===")

    print(
        f"=== Giving up on task after {MAX_ATTEMPTS_PER_TASK} attempts: "
        f"{task['text']} — stopping run for human review ==="
    )
    return False


def main():
    for _ in range(MAX_TASKS_PER_RUN):
        lines, tasks = load_tasks()
        pending = [t for t in tasks if not t["done"]]
        if not pending:
            print("\nNo unchecked tasks remain in spec.md. Stopping.")
            break

        task = pending[0]
        if not run_task_with_retries(task):
            break


if __name__ == "__main__":
    main()

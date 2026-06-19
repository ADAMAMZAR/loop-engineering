import os
import re
import json
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


def run_shell(command):
    result = subprocess.run(command, shell=True, cwd=WORKDIR, capture_output=True, text=True, timeout=30)
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


def run_task(task_text):
    """One fresh, stateless agent instance implementing a single spec task.

    A brand-new `messages` list means this conversation has no memory of
    any other task the loop has run — the only things that persist across
    tasks are spec.md (which task is checked off) and the git log (what
    actually got committed). That's the externally-persisted state the
    Ralph pattern relies on instead of a long-lived conversation.
    """
    messages = [
        {
            "role": "user",
            "content": (
                f"Implement this task from spec.md: {task_text}\n\n"
                "Use the available tools to read/write files and run shell "
                "commands as needed. Verify your work by running it before "
                "you finish."
            ),
        }
    ]
    while True:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=1024,
            tools=tools,
            messages=messages,
        )
        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        if message.content:
            print(f"\n--- assistant says ---\n{message.content}")

        if not message.tool_calls:
            return message.content

        for tool_call in message.tool_calls:
            result = execute_tool_call(tool_call)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                }
            )


TASK_LINE_RE = re.compile(r"^- \[( |x)\] (.+)$")


def load_tasks():
    with open(SPEC_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
    tasks = []
    for i, line in enumerate(lines):
        match = TASK_LINE_RE.match(line.rstrip("\n"))
        if match:
            tasks.append({"line_index": i, "done": match.group(1) == "x", "text": match.group(2)})
    return lines, tasks


def mark_task_done(lines, line_index):
    lines[line_index] = lines[line_index].replace("- [ ]", "- [x]", 1)
    with open(SPEC_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)


def commit_task(task_text):
    subprocess.run(["git", "add", "-A"], cwd=WORKDIR, check=True)
    subprocess.run(["git", "commit", "-m", f"Ralph: {task_text}"], cwd=WORKDIR, check=True)


def main():
    for _ in range(MAX_TASKS_PER_RUN):
        lines, tasks = load_tasks()
        pending = [t for t in tasks if not t["done"]]
        if not pending:
            print("\nNo unchecked tasks remain in spec.md. Stopping.")
            break

        task = pending[0]
        print(f"\n=== Fresh instance starting task: {task['text']} ===")
        run_task(task["text"])

        lines, _ = load_tasks()  # re-read in case the task itself edited spec.md
        mark_task_done(lines, task["line_index"])
        commit_task(task["text"])
        print(f"=== Checked off and committed: {task['text']} ===")


if __name__ == "__main__":
    main()

import os
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

# The sandbox boundary: file tools may only touch paths inside this directory.
WORKDIR = os.path.abspath(os.path.dirname(__file__))

# Read-only tools execute immediately. Mutating tools stop and ask first.
READ_ONLY_TOOLS = {"read_file", "list_dir"}
MUTATING_TOOLS = {"write_file", "run_shell"}

AUDIT_LOG_PATH = os.path.join(WORKDIR, "audit_log.jsonl")

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
    """Resolve a relative path against WORKDIR and reject anything that escapes it."""
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


# The fixed set of binaries run_shell is allowed to invoke at all. Anything
# else is rejected before a single process gets spawned.
ALLOWED_SHELL_COMMANDS = {"git", "python", "pip", "pytest"}


def run_shell(command):
    """Parse the command into argv and execute it directly (shell=False),
    restricted to ALLOWED_SHELL_COMMANDS.

    cwd pinning alone doesn't stop a command from referencing absolute
    paths or chaining further commands with &&/;/| — those only work
    because a real shell is there to interpret them. With shell=False and
    no shell process involved, those characters become inert literal
    argv entries to the binary itself, not a chain of separate commands.
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


def request_approval(name, args):
    print(f"\n--- APPROVAL REQUIRED: {name}({args}) ---")
    answer = input("Allow this? [y/N] ").strip().lower()
    return answer == "y"


def execute_tool_call(tool_call):
    name = tool_call.function.name
    args = json.loads(tool_call.function.arguments)

    if name in MUTATING_TOOLS:
        approved = request_approval(name, args)
        log_event({"tool": name, "args": args, "decision": "approved" if approved else "denied"})
        if not approved:
            return "Denied by user."
    else:
        log_event({"tool": name, "args": args, "decision": "auto"})

    print(f"\n--- executing tool: {name}({args}) ---")
    try:
        result = TOOL_FUNCTIONS[name](**args)
    except Exception as e:
        result = f"Error: {e}"
    print(f"--- result: {result} ---")
    return str(result)


# Bounds on the run as a whole, independent of the per-tool approval gate:
# a model that keeps requesting (approved or auto-run) tools forever would
# otherwise loop — and spend — without limit. These are the harness's own
# blast-radius limit, not something the model can be talked past.
MAX_ITERATIONS = 20
MAX_TOKENS_PER_RUN = 50_000


def record_usage(response, tokens_used):
    """Add this response's token usage to the running total. Returns the
    new total; the caller decides what to do once it exceeds the budget.
    """
    usage = getattr(response, "usage", None)
    tokens = getattr(usage, "total_tokens", 0) if usage else 0
    return tokens_used + tokens


def main():
    messages = [
        {
            "role": "user",
            "content": (
                "List the files in the current directory, read sample.txt, "
                "then write a one-sentence summary of it to summary.txt."
            ),
        }
    ]

    tokens_used = 0
    for iteration in range(1, MAX_ITERATIONS + 1):
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=1024,
            tools=tools,
            messages=messages,
        )
        tokens_used = record_usage(response, tokens_used)
        if tokens_used > MAX_TOKENS_PER_RUN:
            print(
                f"\n--- stopping: token budget exceeded "
                f"({tokens_used}/{MAX_TOKENS_PER_RUN}) ---"
            )
            break

        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        if message.content:
            print(f"\n--- assistant says ---\n{message.content}")

        if not message.tool_calls:
            print("\n--- done: model stopped requesting tools ---")
            break

        for tool_call in message.tool_calls:
            result = execute_tool_call(tool_call)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                }
            )
    else:
        print(f"\n--- stopping: hit the {MAX_ITERATIONS}-iteration cap ---")


if __name__ == "__main__":
    main()

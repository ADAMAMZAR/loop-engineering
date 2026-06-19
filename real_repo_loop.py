import os
import sys
import json
import logging
import argparse
import subprocess
import datetime
from dotenv import load_dotenv
import openai
from openai import OpenAI

import agent_shell
from agent_secrets import has_api_key, resolve_api_key
from agent_logging import configure_logging

load_dotenv()

logger = logging.getLogger(__name__)

# --- DeepSeek (commented out) ---
# Verified against the real API: this base_url/model combination is
# authenticated and recognized correctly (a live request reached the model
# and failed only on account balance - HTTP 402 - not on auth or an unknown
# model error). Swap api_key= to agent_secrets.resolve_api_key() too if you
# want the GOOGLE_API_KEY_FILE fallback for this key as well.
# client = OpenAI(
#     base_url="https://api.deepseek.com",
#     api_key=os.environ.get("DEEPSEEK_API_KEY")
# )
# MODEL = "deepseek-chat"

# --- Google AI Studio (Gemini), via its OpenAI-compatible endpoint ---
client = OpenAI(
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    api_key=resolve_api_key()
)
MODEL = "gemini-2.5-flash"


WORKDIR = os.path.abspath(os.path.dirname(__file__))
AUDIT_LOG_PATH = os.path.join(WORKDIR, "real_repo_audit.jsonl")

READ_ONLY_TOOLS = {"read_file", "list_dir"}
MUTATING_TOOLS = {"write_file", "run_shell"}

DEFAULT_GOAL = (
    "Add an MIT LICENSE file to the root of this repository. "
    "Copyright holder: Adam Amzar. Copyright year: use the current year. "
    "Steps, each as its own separate run_shell call so they can be reviewed "
    "individually: (1) write the LICENSE file, (2) `git add LICENSE`, "
    "(3) `git commit -m \"Add MIT license\"`, (4) `git push`. "
    "Do not combine these into one shell command."
)


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Run an approval-gated agent against this real repo, with a "
            "stricter confirmation gate before any git push."
        )
    )
    parser.add_argument(
        "goal",
        nargs="?",
        default=DEFAULT_GOAL,
        help="What you want the agent to do. Defaults to the MIT-license demo goal if omitted.",
    )
    return parser

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


# This is the highest-stakes script in the repo (it can push to the real,
# public remote), so it gets the same allowlisted, shell=False run_shell as
# safe_harness.py and ralph_loop.py, on top of the push-specific approval
# gate in execute_tool_call below. Unlike the other two scripts, "push" is
# added to the allowed git subcommands here, since this script's whole job
# is git add/commit/push and that gate already exists separately.
ALLOWED_GIT_SUBCOMMANDS = agent_shell.DEFAULT_ALLOWED_GIT_SUBCOMMANDS | {"push"}


def run_shell(command):
    return agent_shell.run_shell(
        command, WORKDIR, allowed_git_subcommands=ALLOWED_GIT_SUBCOMMANDS
    )


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


def request_push_approval(command):
    """A stricter, separate gate for the one action that's hard to take back:
    pushing to a remote that other people (or just future-you) can see.
    Generic mutating-tool approval already happened for this run_shell call —
    this is a second, more deliberate confirmation specifically for the push,
    with the actual outgoing diff shown so the approval is informed.
    """
    print("\n--- PUSH REQUESTED ---")
    print(f"Command: {command}")
    diff = subprocess.run(
        ["git", "diff", "--stat", "origin/main..HEAD"],
        cwd=WORKDIR, capture_output=True, text=True,
    )
    print("Outgoing changes (origin/main..HEAD):")
    print(diff.stdout or "(no diff output — check manually if this looks wrong)")
    answer = input("Type PUSH to confirm, anything else cancels: ").strip()
    return answer == "PUSH"


def execute_tool_call(tool_call):
    name = tool_call.function.name
    args = json.loads(tool_call.function.arguments)

    if name == "run_shell" and "push" in args.get("command", ""):
        approved = request_push_approval(args["command"])
        log_event({"tool": name, "args": args, "decision": "push_approved" if approved else "push_denied"})
        if not approved:
            return "Push denied by user."
    elif name in MUTATING_TOOLS:
        approved = request_approval(name, args)
        log_event({"tool": name, "args": args, "decision": "approved" if approved else "denied"})
        if not approved:
            return "Denied by user."
    else:
        log_event({"tool": name, "args": args, "decision": "auto"})

    logger.info("executing tool: %s(%s)", name, args)
    try:
        result = TOOL_FUNCTIONS[name](**args)
    except Exception as e:
        result = f"Error: {e}"
    logger.info("result: %s", result)
    return str(result)


# Same blast-radius reasoning as safe_harness.py, raised slightly higher
# here since the goal genuinely needs several sequential tool calls
# (write LICENSE, git add, git commit, git push) on top of any exploration.
MAX_ITERATIONS = 20
MAX_TOKENS_PER_RUN = 50_000


def record_usage(response, tokens_used):
    usage = getattr(response, "usage", None)
    tokens = getattr(usage, "total_tokens", 0) if usage else 0
    return tokens_used + tokens


def call_model(messages):
    """Wrap the chat-completion call so a network/auth/rate-limit failure
    comes back as data (response, error) instead of an unhandled exception
    that would crash the run with a raw stack trace.
    """
    try:
        return client.chat.completions.create(
            model=MODEL,
            max_tokens=1024,
            tools=tools,
            messages=messages,
        ), None
    except openai.APIError as e:
        return None, str(e)


def main():
    configure_logging()

    if not has_api_key():
        logger.error(
            "GOOGLE_API_KEY is not set. Add it to a .env file in the project "
            "root, set GOOGLE_API_KEY_FILE to point at a file containing it, "
            "or export it in your shell, before running this script."
        )
        sys.exit(1)

    args = build_arg_parser().parse_args()
    messages = [{"role": "user", "content": args.goal}]

    tokens_used = 0
    for iteration in range(1, MAX_ITERATIONS + 1):
        response, error = call_model(messages)
        if error:
            logger.error("stopping: API call failed: %s", error)
            break
        tokens_used = record_usage(response, tokens_used)
        if tokens_used > MAX_TOKENS_PER_RUN:
            logger.warning(
                "stopping: token budget exceeded (%d/%d)", tokens_used, MAX_TOKENS_PER_RUN
            )
            break

        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        if message.content:
            print(f"\n--- assistant says ---\n{message.content}")

        if not message.tool_calls:
            logger.info("done: model stopped requesting tools")
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
        logger.warning("stopping: hit the %d-iteration cap", MAX_ITERATIONS)


if __name__ == "__main__":
    main()

"""Shared run_shell implementation for safe_harness.py, ralph_loop.py, and
real_repo_loop.py.

Beyond restricting which binaries may run at all, git and pip each get a
subcommand-level allowlist too: `git` and `pip` being allowed binaries
doesn't mean every subcommand they expose is safe to let an agent run
unreviewed. `git push`/`config`/`remote`/`clone`/`fetch`/`pull`/`checkout`/
`reset` and `pip install`/`uninstall`/`download` can each do real damage on
their own (push to a remote nobody reviewed, rewrite git config, execute
arbitrary setup.py code, install a malicious package) even with shell=False
already blocking command chaining.

This still isn't a full sandbox: `python -c "<anything>"` is a complete
scripting environment, and no allowlist over argv can constrain what code it
runs. Restricting that further would need real OS-level isolation (a
container, VM, or seccomp profile), which is out of scope here — this
allowlist narrows the blast radius of the *shell command* surface, not
arbitrary code run by an interpreter that's itself allowed to execute.
"""

import os
import shlex
import subprocess

ALLOWED_SHELL_COMMANDS = {"git", "python", "pip", "pytest"}

# No install/uninstall/download anywhere: an agent installing arbitrary
# packages on its own is a supply-chain risk regardless of which script is
# running it. Dependencies belong in requirements.txt, reviewed by a human.
ALLOWED_PIP_SUBCOMMANDS = {"list", "show", "freeze", "check"}

# Local, non-destructive, non-network git operations. Notably excludes
# push, config, remote, clone, fetch, pull, checkout, and reset.
DEFAULT_ALLOWED_GIT_SUBCOMMANDS = {"status", "diff", "log", "show", "add", "commit"}


def run_shell(command, workdir, allowed_git_subcommands=DEFAULT_ALLOWED_GIT_SUBCOMMANDS):
    """Parse the command into argv and execute it directly (shell=False),
    restricted to ALLOWED_SHELL_COMMANDS plus the git/pip subcommand
    allowlists above.

    cwd pinning alone doesn't stop a command from referencing absolute
    paths or chaining further commands with &&/;/| — those only work
    because a real shell is there to interpret them. With shell=False and
    no shell process involved, those characters become inert literal argv
    entries to the binary itself, not a chain of separate commands.
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

    if binary == "git" and len(args) > 1 and args[1] not in allowed_git_subcommands:
        return (
            f"Error: 'git {args[1]}' is not in the allowed git subcommand "
            f"list {sorted(allowed_git_subcommands)}. Rejected before execution."
        )
    if binary == "pip" and len(args) > 1 and args[1] not in ALLOWED_PIP_SUBCOMMANDS:
        return (
            f"Error: 'pip {args[1]}' is not in the allowed pip subcommand "
            f"list {sorted(ALLOWED_PIP_SUBCOMMANDS)}. Rejected before execution."
        )

    result = subprocess.run(
        args, shell=False, cwd=workdir, capture_output=True, text=True, timeout=30
    )
    return f"exit code: {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"

"""Shell-injection guard audit.

The bug class
-------------
Two shapes, same root cause — passing user input through a
shell:

1. **`subprocess.run(..., shell=True)`** with a string command:

       cmd = f"git clone {repo_url}"
       subprocess.run(cmd, shell=True)

   If `repo_url` came from a request param, an attacker can
   inject `; rm -rf / #` and own the runner.

2. **`os.system(cmd)`** — same shape, no `shell=` flag because
   `os.system` ALWAYS uses /bin/sh. Plus it returns the exit
   code, not the output, so usage is rare and almost always a
   smell.

The fix is structural: pass `args` as a list and drop `shell`:

    subprocess.run(["git", "clone", repo_url])

The list form bypasses the shell entirely. The arg array goes
straight to execve; no metacharacter interpretation, no
injection surface.

What this audit checks
----------------------
AST walk over `apps/api/{core,db,middleware,models,routers,
schemas,services,workers}/*.py` plus `apps/worker/*.py` plus
`scripts/*.py`. Flag:

  * `subprocess.run(..., shell=True)` and the same for
    `subprocess.Popen`, `subprocess.call`, `subprocess.check_call`,
    `subprocess.check_output`. Whether or not the cmd is a
    string literal — the audit's bar is "shell=True is asking
    for trouble," not "we proved this exact call is exploitable."
  * `os.system(...)` — every call site, regardless of arg
    shape. The function itself is the smell.

What's NOT checked
------------------
- `subprocess.run([...])` (list arg, no `shell=True`) — safe.
- `subprocess.run("cmd", shell=False)` — explicitly safe (though
  rare).
- Test files — tests that exercise shell-injection defences are
  legitimate.
- f-string + list arg: `subprocess.run([f"git", "clone", url])`.
  The arg-list form already bypasses the shell; embedding an
  f-string in element 0 doesn't change that. We don't flag.

Allowlist
---------
Per-(file, line) entries for legitimate cases (e.g. a sandboxed
admin tool that runs a known constant command via shell for
shell-builtin reasons). Each needs a stated reason.

Same ratchet pattern as the other audits.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_API_ROOT = _REPO_ROOT / "apps" / "api"
_SCAN_ROOTS: list[Path] = [
    _API_ROOT / "core",
    _API_ROOT / "db",
    _API_ROOT / "middleware",
    _API_ROOT / "models",
    _API_ROOT / "routers",
    _API_ROOT / "schemas",
    _API_ROOT / "services",
    _API_ROOT / "workers",
    _API_ROOT / "scripts",
    _REPO_ROOT / "apps" / "worker",
    _REPO_ROOT / "scripts",
]


# Today's baseline. Filled in on first run.
BASELINE_SHELL_INJECTIONS = 0


# Per-(relative_posix_path, line) allowlist. Each entry needs a
# stated reason. An empty rationale silences the gate.
ALLOWLIST: dict[tuple[str, int], str] = {
    # No entries today.
}


# subprocess methods that take a `shell=` kwarg.
_SUBPROCESS_METHODS: frozenset[str] = frozenset(
    {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"}
)


def _scan_files() -> list[Path]:
    out: list[Path] = []
    for root in _SCAN_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            if "tests" in p.parts:
                continue
            out.append(p)
    return sorted(out)


def _is_subprocess_shell_true(node: ast.Call) -> bool:
    """`subprocess.run(..., shell=True)` and friends. Returns
    True when the call's func is `subprocess.<method>` AND any
    keyword `shell=True` is present.
    """
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in _SUBPROCESS_METHODS:
        return False
    # Receiver must be `subprocess` (bare or imported as).
    recv = func.value
    if not isinstance(recv, ast.Name) or recv.id != "subprocess":
        return False
    # Find shell= kwarg.
    for kw in node.keywords:
        if kw.arg != "shell":
            continue
        return isinstance(kw.value, ast.Constant) and kw.value.value is True
    return False


def _is_os_system(node: ast.Call) -> bool:
    """`os.system(...)` — flagged regardless of args."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr != "system":
        return False
    recv = func.value
    return isinstance(recv, ast.Name) and recv.id == "os"


def _scan_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    rel = path.relative_to(_REPO_ROOT).as_posix()
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kind: str | None = None
        if _is_subprocess_shell_true(node):
            kind = "subprocess shell=True"
        elif _is_os_system(node):
            kind = "os.system"
        if kind is None:
            continue
        line = node.lineno
        if (rel, line) in ALLOWLIST:
            continue
        try:
            source_line = text.splitlines()[line - 1].strip()[:80]
        except IndexError:
            source_line = "<unknown>"
        findings.append(f"{rel}:{line}  [{kind}]  {source_line}")
    return findings


def _audit_all() -> list[str]:
    out: list[str] = []
    for path in _scan_files():
        out.extend(_scan_file(path))
    return out


def test_no_shell_injection_call_sites():
    """`subprocess.<method>(..., shell=True)` and `os.system(...)`
    are both shell-injection-prone. Use the list-arg form of
    `subprocess.run` instead — it bypasses the shell entirely.
    """
    findings = _audit_all()
    n = len(findings)
    if n > BASELINE_SHELL_INJECTIONS:
        new = n - BASELINE_SHELL_INJECTIONS
        pytest.fail(
            f"{new} new shell-injection-prone call site(s) "
            f"(total now {n}, baseline {BASELINE_SHELL_INJECTIONS}):\n  "
            + "\n  ".join(findings[:20])
            + (f"\n  … and {n - 20} more" if n > 20 else "")
            + "\n\nReplace with the list-arg form:\n"
            "    # was (shell-injection surface):\n"
            "    subprocess.run(f'git clone {url}', shell=True)\n"
            "    # use (safe — args go straight to execve):\n"
            "    subprocess.run(['git', 'clone', url])\n\n"
            "If a shell built-in is genuinely required (`cd`, "
            "redirection, pipes), use a list with `bash -c`:\n"
            "    subprocess.run(['bash', '-c', script_constant])\n"
            "where `script_constant` is a literal — not a string "
            "interpolated with user input.\n\n"
            "If the call is genuinely safe (admin-only, constant "
            "command, sandboxed runner), add to ALLOWLIST with a "
            "stated reason."
        )
    if n < BASELINE_SHELL_INJECTIONS:
        pytest.fail(
            f"Shell-injection count dropped from "
            f"{BASELINE_SHELL_INJECTIONS} to {n}. 🎉 Update "
            f"`BASELINE_SHELL_INJECTIONS` to {n}."
        )


def test_audit_recognises_documented_shapes():
    """Defensive: positive + negative AST fixtures."""
    # Positive: subprocess.run with shell=True.
    pos1 = ast.parse("import subprocess\nsubprocess.run('ls', shell=True)\n")
    calls = [n for n in ast.walk(pos1) if isinstance(n, ast.Call) and _is_subprocess_shell_true(n)]
    assert len(calls) == 1

    # Positive: os.system.
    pos2 = ast.parse("import os\nos.system('ls')\n")
    calls = [n for n in ast.walk(pos2) if isinstance(n, ast.Call) and _is_os_system(n)]
    assert len(calls) == 1

    # Positive: subprocess.Popen with shell=True.
    pos3 = ast.parse("import subprocess\nsubprocess.Popen(['x'], shell=True)\n")
    calls = [n for n in ast.walk(pos3) if isinstance(n, ast.Call) and _is_subprocess_shell_true(n)]
    assert len(calls) == 1

    # Negative: list-arg, no shell=True.
    neg1 = ast.parse("import subprocess\nsubprocess.run(['ls', '-la'])\n")
    calls = [n for n in ast.walk(neg1) if isinstance(n, ast.Call) and _is_subprocess_shell_true(n)]
    assert calls == []

    # Negative: shell=False explicit.
    neg2 = ast.parse("import subprocess\nsubprocess.run('ls', shell=False)\n")
    calls = [n for n in ast.walk(neg2) if isinstance(n, ast.Call) and _is_subprocess_shell_true(n)]
    assert calls == []

    # Negative: unrelated `.system` method (not on os).
    neg3 = ast.parse("self.system.run()\n")
    calls = [n for n in ast.walk(neg3) if isinstance(n, ast.Call) and _is_os_system(n)]
    assert calls == []


def test_allowlist_entries_actually_correspond_to_real_calls():
    """Defensive: stale ALLOWLIST entries silently mask future
    regressions.
    """
    if not ALLOWLIST:
        return
    real_calls: set[tuple[str, int]] = set()
    for path in _scan_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _is_subprocess_shell_true(node) or _is_os_system(node):
                real_calls.add((rel, node.lineno))
    stale = [k for k in ALLOWLIST if k not in real_calls]
    assert not stale, f"Stale ALLOWLIST entries: {stale}."

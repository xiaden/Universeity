"""No-shell-interpolation architecture tests (Phase C, P1-S4).

Enforces the DD hard rule that no untrusted input is ever interpolated into a
shell: array-only argv everywhere, no ``shell=True``, no ``os.system`` /
``os.popen``. These are static/architecture gates over the whole ``src`` tree so
a future regression (someone reaching for a shell) fails loudly.
"""

from __future__ import annotations

import pathlib

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "umd"


def _py_files() -> list[pathlib.Path]:
    return sorted(_SRC.rglob("*.py"))


def test_no_shell_true_anywhere() -> None:
    offenders = [str(f) for f in _py_files() if "shell=True" in f.read_text(encoding="utf-8")]
    assert not offenders, f"shell=True found in: {offenders}"


def test_no_os_system_or_popen() -> None:
    bad = ["os.system(", "os.popen("]
    offenders = [
        f"{f}:{tok}" for f in _py_files() for tok in bad if tok in f.read_text(encoding="utf-8")
    ]
    assert not offenders, f"shell-style API found: {offenders}"


def test_subprocess_calls_use_array_argv() -> None:
    """Every ``subprocess.run``/``Popen`` must be an argv list, never a string."""
    bad: list[str] = []
    for f in _py_files():
        src = f.read_text(encoding="utf-8")
        for i, line in enumerate(src.splitlines(), start=1):
            if "subprocess.run(" in line or "Popen(" in line:
                # Heuristic: `shell=` in the same call expression means string cmd.
                window = src.splitlines()[i : i + 6] if i < len(src.splitlines()) else []
                if any("shell=" in w for w in window):
                    bad.append(f"{f}:{i}")
    assert not bad, f"subprocess calls that may take a string command: {bad}"

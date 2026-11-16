#!/usr/bin/env python3
"""make_venv.py: give this p4 checkout its one Python environment, .venv/ at its root, with everything p4's scripts and
the p4-model skill run: ezexe/phi's packages phi_prune, phi_rank, phi_store and phi_model, torch for the .pt ranker
and the ensemble of shard models in phi_rank/tree.py, and the anthropic SDK for the teacher.

    python3 scripts/make_venv.py                  # create or update .venv, with ezexe/phi from ../phi, else GitHub
    python3 scripts/make_venv.py --phi <path>     # ezexe/phi from that checkout, installed editable
    python3 scripts/make_venv.py --check          # only report what .venv has

Then use .venv/bin/python, or .venv\\Scripts\\python.exe on Windows, as in `.venv/bin/python -m phi_model check
--project <repo>`. An existing .venv is reused and topped up, never recreated. torch comes from PyTorch's CPU wheel
index, since the p4 models train and serve on the CPU, else from PyPI; --cuda takes PyPI's default build instead.

Where no torch build exists for the machine, as on an Intel Mac, whose last PyTorch wheels are 2.2 for Python 3.12 at
most, .venv is finished without it: ezexe/phi is installed without its torch dependency, and everything retrieval
serves still runs, since `phi_model check` reads the JSON ranker, the labels and the notices and says the .pt ranker
is not checked. To get torch on such a Mac, build .venv from a Python 3.12: remove .venv and run
`python3.12 scripts/make_venv.py`.

It stops before it makes or tops up .venv when the Python that runs ezexe/phi there, .venv's own or else the one
running this script, is older than the requires-python of the ezexe/phi checkout it installs, and an ezexe/phi from
GitHub, whose pyproject.toml is not at hand, is held to PHI_PYTHON.

The plugins' hooks never need .venv: they run on the system python3, standard library only. This script uses the
standard library only too, so it runs before .venv exists.
"""

import argparse
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
PHI_GIT = "git+https://github.com/ezexe/phi"
TORCH_CPU = "https://download.pytorch.org/whl/cpu"
CHECK = ("torch", "numpy", "phi_prune", "phi_rank", "phi_store", "phi_model", "anthropic")
NEED_TORCH = ("torch", "phi_prune", "phi_rank")     # what cannot import on a machine with no torch build
PHI_PYTHON = (3, 10, 0)     # ezexe/phi's requires-python, for an ezexe/phi from GitHub
LOWER = re.compile(r"(>=|~=|==|>)\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?")     # a version specifier that sets a lower bound


def python_of(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(*cmd) -> int:
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd]).returncode


def missing(py: Path):
    """The modules of CHECK the environment cannot import, each tried on its own."""
    out = []
    for mod in CHECK:
        r = subprocess.run([str(py), "-c", f"import {mod}"], capture_output=True, text=True)
        if r.returncode:
            out.append(mod)
    return out


def phi_source(given):
    """An editable ezexe/phi checkout, the given one or else ../phi beside this checkout, or the GitHub URL."""
    for cand in ([Path(given)] if given else []) + [ROOT.parent / "phi"]:
        if (cand / "pyproject.toml").is_file() and 'name = "phi-prune"' in (cand / "pyproject.toml").read_text(encoding="utf-8"):
            return cand.resolve(), True
    if given:
        raise SystemExit(f"make_venv.py: {given} is not an ezexe/phi checkout, since no pyproject.toml there names "
                         "phi-prune")
    return PHI_GIT, False


def python_floor(src, editable):
    """The oldest Python ezexe/phi installs on, as major, minor and micro: the highest lower bound in the
    requires-python of a checkout's pyproject.toml, None when the checkout sets none, and PHI_PYTHON for GitHub."""
    if not editable:
        return PHI_PYTHON
    m = re.search(r"""(?m)^\s*requires-python\s*=\s*(["'])(.*?)\1""",
                  (Path(src) / "pyproject.toml").read_text(encoding="utf-8"))
    bounds = []
    for op, *parts in LOWER.findall(m.group(2) if m else ""):
        v = tuple(int(x or 0) for x in parts)
        bounds.append(v[:2] + (v[2] + 1,) if op == ">" else v)
    return max(bounds) if bounds else None


def venv_python(py):
    """The version .venv's own interpreter reports, as major, minor and micro, or None when it does not answer."""
    try:
        out = subprocess.run([str(py), "-c", "import sys; print(*sys.version_info[:3])"], capture_output=True,
                             text=True).stdout.split()
    except OSError:
        return None
    return tuple(int(x) for x in out) if len(out) == 3 and all(x.isdigit() for x in out) else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Create or update this p4 checkout's .venv")
    ap.add_argument("--phi", help="an ezexe/phi checkout to install editable; by default ../phi when it exists, "
                    "else GitHub")
    ap.add_argument("--cuda", action="store_true", help="torch's default PyPI build instead of the CPU wheels")
    ap.add_argument("--check", action="store_true", help="only report which modules .venv lacks")
    a = ap.parse_args(argv)
    if sys.version_info < (3, 7):
        raise SystemExit(f"make_venv.py: this script needs Python 3.7 or newer, and this is Python "
                         f"{sys.version.split()[0]}")
    py = python_of(VENV)
    if a.check:
        if not py.exists():
            print(f"no .venv at {VENV}: run python3 scripts/make_venv.py")
            return 1
        gone = missing(py)
        if gone and set(gone) <= set(NEED_TORCH) and "torch" in gone:
            print(f"{py}: everything but torch imports, so the .pt ranker and the ensemble of shard models are off here")
            return 0
        print(f"{py}: " + ("everything imports" if not gone else "missing " + ", ".join(gone)))
        return 1 if gone else 0
    src, editable = phi_source(a.phi)
    floor = python_floor(src, editable)
    have = venv_python(py) if py.exists() else tuple(sys.version_info[:3])
    if floor and have and have < floor:
        need = ".".join(map(str, floor if floor[2] else floor[:2]))
        raise SystemExit(f"make_venv.py: ezexe/phi needs Python {need} or newer, and " + (
            f".venv runs Python {'.'.join(map(str, have))}; remove .venv and run make_venv.py from a newer Python"
            if py.exists() else f"this is Python {sys.version.split()[0]}"))
    if not py.exists():
        if run(sys.executable, "-I", "-m", "venv", VENV):
            return 1
    else:
        print(f"reusing {VENV}")
    if run(py, "-m", "pip", "install", "-q", "--upgrade", "pip"):
        print("make_venv.py: the step above failed; .venv is left as it is")
        return 1
    torch_ok = "torch" not in missing(py)
    if not torch_ok:
        tries = ([[]] if a.cuda else [["--index-url", TORCH_CPU], []])     # the CPU wheels, then PyPI
        torch_ok = any(run(py, "-m", "pip", "install", "-q", "torch", *t) == 0 for t in tries)
        if not torch_ok:
            print(f"make_venv.py: no torch build for this machine, {platform.machine()} on Python "
                  f"{'.'.join(map(str, (have or tuple(sys.version_info[:3]))[:2]))}, so .venv is finished "
                  f"without it")
    steps = []
    if not torch_ok:
        steps.append([py, "-m", "pip", "install", "-q", "numpy"])    # ezexe/phi's other dependency, without torch
    steps.append([py, "-m", "pip", "install", "-q"] + ([] if torch_ok else ["--no-deps"])
                 + (["-e", src] if editable else [src]))
    steps.append([py, "-m", "pip", "install", "-q", "-r", REQUIREMENTS])
    for s in steps:
        if run(*s):
            print("make_venv.py: the step above failed; .venv is left as it is")
            return 1
    gone = [m for m in missing(py) if torch_ok or m not in NEED_TORCH]
    if gone:
        print(f"make_venv.py: .venv still cannot import {', '.join(gone)}")
        return 1
    ver = subprocess.run([str(py), "-c", "import sys; print(sys.version.split()[0])"], capture_output=True,
                         text=True).stdout.strip()
    tv = subprocess.run([str(py), "-c", "import torch; print(torch.__version__)"], capture_output=True,
                        text=True).stdout.strip() if torch_ok else ""
    print(f"ready: {py}, Python {ver}; " + (f"torch {tv}" if torch_ok else "no torch, so the .pt ranker and the ensemble "
          "of shard models are off on this machine, while retrieval and phi_model check run")
          + f"; ezexe/phi {'editable from ' + str(src) if editable else 'from ' + src}")
    print(f"  {py} -m phi_model check --project <repository or its .claude/p4>")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""make_make_venv.py: give this p4 checkout its one Python environment, .venv/ at its root, with everything p4's scripts and
the p4-model skill run: phi (phi_prune, phi_rank, phi_store, phi_serve, phi_model) and torch for the .pt ranker and
the node tree, the anthropic SDK for the teacher and the paid experiments, ipykernel for the notebooks.

    python3 scripts/make_venv.py                  # create or update .venv; phi from a sibling ../phi checkout, else GitHub
    python3 scripts/make_venv.py --phi <path>     # phi from that checkout (editable)
    python3 scripts/make_venv.py --check          # only report what .venv has

Then use .venv/bin/python (Windows: .venv\\Scripts\\python.exe), e.g. `.venv/bin/python -m phi_model check
--project <repo>`. An existing .venv is reused and topped up, never recreated. torch comes from PyTorch's CPU wheel
index (the p4 models train and serve on the CPU; --cuda takes PyPI's default build instead), else from PyPI.

Where no torch build exists for the machine (PyTorch's last Intel-Mac wheels are 2.2, for Python 3.12 at most), .venv
is finished without it: phi is installed without its torch dependency, and everything recall serves still runs
(`phi_model check` reads the JSON ranker, the labels and the notices, and says the .pt ranker is not checked). To get
torch on such a Mac, build .venv from a Python 3.12: remove .venv and run `python3.12 scripts/make_venv.py`.

The plugins' hooks never need this: they run on the system python3, standard library only. Standard library only, so
it runs before .venv exists.
"""

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
PHI_GIT = "git+https://github.com/ezexe/phi"
TORCH_CPU = "https://download.pytorch.org/whl/cpu"
CHECK = ("torch", "numpy", "phi_prune", "phi_rank", "phi_store", "phi_serve", "phi_model", "anthropic")
NEED_TORCH = ("torch", "phi_prune", "phi_rank", "phi_serve")     # what cannot import on a machine with no torch build


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
    """An editable phi checkout (the given one, else ../phi beside this checkout), or the GitHub URL."""
    for cand in ([Path(given)] if given else []) + [ROOT.parent / "phi"]:
        if (cand / "pyproject.toml").is_file() and 'name = "phi-prune"' in (cand / "pyproject.toml").read_text(encoding="utf-8"):
            return cand.resolve(), True
    if given:
        raise SystemExit(f"make_venv.py: {given} is not a phi checkout (no pyproject.toml naming phi-prune)")
    return PHI_GIT, False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Create or update this p4 checkout's .venv")
    ap.add_argument("--phi", help="a phi checkout to install editable (default: ../phi when it exists, else GitHub)")
    ap.add_argument("--cuda", action="store_true", help="torch's default PyPI build instead of the CPU wheels")
    ap.add_argument("--check", action="store_true", help="only report which modules .venv lacks")
    a = ap.parse_args(argv)
    py = python_of(VENV)
    if a.check:
        if not py.exists():
            print(f"no .venv at {VENV}: run python3 scripts/make_venv.py")
            return 1
        gone = missing(py)
        if gone and set(gone) <= set(NEED_TORCH) and "torch" in gone:
            print(f"{py}: everything but torch imports (no torch: the .pt ranker and the node tree are off here)")
            return 0
        print(f"{py}: " + ("everything imports" if not gone else "missing " + ", ".join(gone)))
        return 1 if gone else 0
    if sys.version_info < (3, 9):
        raise SystemExit(f"make_venv.py: Python 3.9 or newer is needed for phi (this is {sys.version.split()[0]})")
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
            print(f"make_venv.py: no torch build for this machine ({platform.machine()}, Python "
                  f"{sys.version_info.major}.{sys.version_info.minor}); finishing .venv without it")
    src, editable = phi_source(a.phi)
    steps = []
    if not torch_ok:
        steps.append([py, "-m", "pip", "install", "-q", "numpy"])    # phi's other dependency, without torch
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
    print(f"ready: {py} (Python {ver}; " + (f"torch {tv}" if torch_ok else "no torch: the .pt ranker and the node tree "
          "are off on this machine; recall and phi_model check run") + f"; phi {'editable from ' + str(src) if editable else 'from ' + src})")
    print(f"  {py} -m phi_model check --project <repository or its .claude/p4>")
    return 0


if __name__ == "__main__":
    sys.exit(main())

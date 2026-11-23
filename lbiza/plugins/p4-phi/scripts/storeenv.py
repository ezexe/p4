#!/usr/bin/env python3
"""storeenv.py: the Python environment of a repository's store, `.venv` in the `.claude/p4` of its main checkout,
with what p4-phi's paid batches and ezexe/phi's p4-model skill run on: ezexe/phi's packages phi_prune, phi_rank,
phi_store and phi_model, torch for the .pt ranker and the ensemble of shard models in phi_rank/tree.py, and the
anthropic SDK for teacher.py. `p4.py venv` runs it:

    python -I -X utf8 p4.py venv                 # create or top up it, with ezexe/phi from ../phi, else GitHub
    python -I -X utf8 p4.py venv --p4 <dir>      # of that repository, or of the repository whose .claude/p4 it is
    python -I -X utf8 p4.py venv --phi <path>    # ezexe/phi from that checkout, installed editable
    python -I -X utf8 p4.py venv --no-torch      # leave torch out
    python -I -X utf8 p4.py venv --check         # only report what it has

Each repository has its own, as each Python project has, and nothing builds it unasked: catchup.py names a missing
one to ezexe at a session's start, with the whole command. A session in a git worktree, or in a folder of the
repository, resolves to the main checkout's store by p4conf.main_root, so a worktree builds no second copy. Python's
venv page, https://docs.python.org/3/library/venv.html, says an environment is "Not considered as movable or
copyable – you just recreate the same environment in the target location", so none is copied between repositories
or into a worktree, and one whose repository moved is removed and built again.

Use it by its interpreter's full path, `.claude/p4/.venv/bin/python` or on Windows
`.claude\\p4\\.venv\\Scripts\\python.exe`, as in `<that python> -m phi_model check --project <repo>`: "You don't
specifically need to activate a virtual environment, as you can just specify the full path to that environment's
Python interpreter when invoking Python", by the same page. An existing environment is reused and topped up, never
recreated. torch comes from PyTorch's CPU wheel index, since the p4 models train and serve on the CPU, else from
PyPI; --cuda takes PyPI's default build instead.

--no-torch leaves torch out, since each repository's environment holds its own copy of it: ezexe/phi is installed
without its torch dependency, and everything retrieval serves still runs, since `phi_model check` reads the JSON
ranker, the labels and the notices and says the .pt ranker is not checked. Where no torch build exists for the
machine, the environment is finished the same way. An Intel Mac always takes that route: ezexe/phi needs torch 2.4.1
or newer, and PyPI's last torch for macOS on x86_64 is 2.2.2, so no torch is asked for there.

It stops before it makes or tops up .venv when the Python that runs ezexe/phi there, .venv's own or else the one
running this script, is older than the requires-python in the pyproject.toml of the ezexe/phi it installs: the
checkout's own, or for an ezexe/phi from GitHub the one on GitHub, read before the install, with PHI_PYTHON in its
place when that file cannot be read or sets no lower bound this script reads.

The environment never enters the store's git: hook.py's GITIGNORE names `.venv/`, and ignore() writes into the
environment the `.gitignore` holding `*` that Python 3.13's venv writes there, where an older Python wrote none.
deps.py never reads it as the project's dependencies, since it enters no folder named `.claude`.

The plugins' hooks never need it: they run on the system python3, standard library only. This script uses the
standard library only too, so it runs before the environment exists.
"""

import argparse
import http.client
import os
import platform
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402

NAME = ".venv"      # the environment's folder, in the store
ROOT = None         # the main checkout of the repository the environment is for; main() sets it from place()
VENV = None         # the environment: ROOT's .claude/p4/.venv; main() sets it from place()
PACKAGES = ("anthropic>=2.6",)      # p4's own needs beyond ezexe/phi and torch: the SDK p4-phi's teacher.py calls
PHI_FOLDER = "lbiza"      # the folder of ezexe/phi that holds its pyproject.toml, its packages and its tests
PHI_GIT = "git+https://github.com/ezexe/phi#subdirectory=" + PHI_FOLDER
TORCH_CPU = "https://download.pytorch.org/whl/cpu"
CHECK = ("torch", "numpy", "phi_prune", "phi_rank", "phi_store", "phi_model", "anthropic")
NEED_TORCH = ("torch", "phi_prune", "phi_rank")     # what cannot import on a machine with no torch build
PHI_PYPROJECT = f"https://raw.githubusercontent.com/ezexe/phi/HEAD/{PHI_FOLDER}/pyproject.toml"     # of what PHI_GIT installs
PHI_PYTHON = (3, 11, 0)     # ezexe/phi's requires-python, in its place when GitHub's file gives none
LOWER = re.compile(r"(>=|~=|==|>)\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?")     # a version specifier that sets a lower bound


def place(given=None):
    """(the main checkout of the repository, its store's environment) for the folder given, else CLAUDE_PROJECT_DIR,
    else the working directory. A store named by its own folder, `.claude/p4`, or by a folder inside it, stands for
    the repository it is in, since the store is a git repository of its own and main_root would stop at it. A git
    worktree and a folder of the repository give the main checkout's, by p4conf.main_root, so a worktree has no
    environment of its own; outside a repository the folder itself is the root."""
    base = d = os.path.abspath(given or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    while True:                                 # the nearest .claude/p4 at or above the folder: its repository
        up = os.path.dirname(d)
        if up == d:
            break
        if os.path.basename(d) == "p4" and os.path.basename(up) == ".claude":
            base = os.path.dirname(up)
            break
        d = up
    root = Path(p4conf.main_root(base)[0])
    return root, root / ".claude" / "p4" / NAME


def command(root):
    """The whole command that builds the environment of the repository at `root`, in the form catchup.py's
    sync_command gives the one that syncs the store."""
    return f"python -I -X utf8 \"{os.path.join(HERE, 'p4.py')}\" venv --p4 \"{root}\"".replace("\\", "/")


def intel_mac():
    """True on macOS on x86_64, where PyPI's last torch, 2.2.2, is older than the 2.4.1 ezexe/phi needs."""
    return platform.system() == "Darwin" and platform.machine() == "x86_64"


def python_of(venv: Path) -> Path:
    return Path(venv) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ignore(venv):
    """Write the environment's own .gitignore, holding `*`, where it has none: Python 3.13's venv writes one, and an
    older Python does not. A file there is left as it is, and nothing is written where no environment is."""
    gi = Path(venv) / ".gitignore"
    if Path(venv).is_dir() and not gi.exists():
        gi.write_text("# written by p4-phi's storeenv.py, as Python 3.13's venv writes it\n*\n", encoding="utf-8")


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
    """The folder of an ezexe/phi checkout to install editable, which is the checkout's lbiza/, where its
    pyproject.toml is: of the given checkout alone when one is given, else of ../phi beside the repository's main
    checkout, or else the GitHub URL, which names the same folder. A path that names that folder itself is taken as
    it is."""
    for cand in [Path(given)] if given else [ROOT.parent / "phi"]:
        for folder in (cand / PHI_FOLDER, cand):
            file = folder / "pyproject.toml"
            if file.is_file() and 'name = "phi-prune"' in file.read_text(encoding="utf-8"):
                return folder.resolve(), True
    if given:
        raise SystemExit(f"p4.py venv: {given} is not an ezexe/phi checkout, since no pyproject.toml there or in "
                         f"its {PHI_FOLDER}/ names phi-prune")
    return PHI_GIT, False


def github_pyproject():
    """The pyproject.toml of the ezexe/phi on GitHub, which PHI_GIT installs, or None when it cannot be read."""
    try:
        with urllib.request.urlopen(PHI_PYPROJECT, timeout=10) as r:
            return r.read().decode("utf-8")
    except (OSError, ValueError, http.client.HTTPException):
        return None


def python_floor(src, editable):
    """The oldest Python ezexe/phi installs on, as major, minor and micro. For a checkout, the lower bound its
    pyproject.toml sets, or None when it sets none; for an ezexe/phi from GitHub, the lower bound of the
    pyproject.toml there, or PHI_PYTHON when that file cannot be read or sets no lower bound this script reads."""
    if editable:
        return lower_bound((Path(src) / "pyproject.toml").read_text(encoding="utf-8"))
    return lower_bound(github_pyproject() or "") or PHI_PYTHON


def lower_bound(text):
    """The highest lower bound in the requires-python line of a pyproject.toml's text, as major, minor and micro,
    or None when the line is missing or sets no lower bound."""
    m = re.search(r"""(?m)^\s*requires-python\s*=\s*(["'])(.*?)\1""", text)
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
    global ROOT, VENV
    ap = argparse.ArgumentParser(prog="p4.py venv",
                                 description="Create or top up the Python environment of a repository's store")
    ap.add_argument("--p4", help="the repository, or its .claude/p4; by default CLAUDE_PROJECT_DIR, else the "
                    "working directory")
    ap.add_argument("--phi", help="an ezexe/phi checkout to install editable; by default ../phi beside the "
                    "repository's main checkout when it exists, else GitHub")
    torch = ap.add_mutually_exclusive_group()
    torch.add_argument("--cuda", action="store_true", help="torch's default PyPI build instead of the CPU wheels")
    torch.add_argument("--no-torch", action="store_true", help="leave torch out: retrieval and phi_model check run "
                       "without it, and the .pt ranker and the ensemble of shard models are off")
    ap.add_argument("--check", action="store_true", help="only report which modules .venv lacks")
    a = ap.parse_args(argv)
    if sys.version_info < (3, 7):
        raise SystemExit(f"p4.py venv: this script needs Python 3.7 or newer, and this is Python "
                         f"{sys.version.split()[0]}")
    ROOT, VENV = place(a.p4)
    py = python_of(VENV)
    if a.check:
        if not py.exists():
            print(f"no environment at {VENV}: run {command(ROOT)}")
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
        raise SystemExit(f"p4.py venv: ezexe/phi needs Python {need} or newer, and " + (
            f".venv runs Python {'.'.join(map(str, have))}; remove .venv, the folder {VENV}, and run this again "
            f"from a newer Python" if py.exists() else f"this is Python {sys.version.split()[0]}"))
    if not py.exists():
        if run(sys.executable, "-I", "-m", "venv", VENV):
            return 1
    else:
        print(f"reusing {VENV}")
    ignore(VENV)
    if run(py, "-m", "pip", "install", "-q", "--upgrade", "pip"):
        print("p4.py venv: the step above failed; .venv is left as it is")
        return 1
    if intel_mac():
        torch_ok = False
        print("p4.py venv: an Intel Mac has no torch ezexe/phi accepts, since PyPI's last torch for it is 2.2.2 and "
              "ezexe/phi needs 2.4.1 or newer, so .venv is finished without it")
    else:
        torch_ok = "torch" not in missing(py)
        if a.no_torch and not torch_ok:
            print("p4.py venv: --no-torch, so no torch is asked for and .venv is finished without it")
    if not torch_ok and not intel_mac() and not a.no_torch:
        tries = ([[]] if a.cuda else [["--index-url", TORCH_CPU], []])     # the CPU wheels, then PyPI
        torch_ok = any(run(py, "-m", "pip", "install", "-q", "torch", *t) == 0 for t in tries)
        if not torch_ok:
            print(f"p4.py venv: no torch build for this machine, {platform.machine()} on Python "
                  f"{'.'.join(map(str, (have or tuple(sys.version_info[:3]))[:2]))}, so .venv is finished "
                  f"without it")
    steps = []
    if not torch_ok:
        steps.append([py, "-m", "pip", "install", "-q", "numpy"])    # ezexe/phi's other dependency, without torch
    steps.append([py, "-m", "pip", "install", "-q"] + ([] if torch_ok else ["--no-deps"])
                 + (["-e", src] if editable else [src]))
    steps.append([py, "-m", "pip", "install", "-q", *PACKAGES])
    for s in steps:
        if run(*s):
            print("p4.py venv: the step above failed; .venv is left as it is")
            return 1
    gone = [m for m in missing(py) if torch_ok or m not in NEED_TORCH]
    if gone:
        print(f"p4.py venv: .venv still cannot import {', '.join(gone)}")
        return 1
    ver = subprocess.run([str(py), "-c", "import sys; print(sys.version.split()[0])"], capture_output=True,
                         text=True).stdout.strip()
    tv = subprocess.run([str(py), "-c", "import torch; print(torch.__version__)"], capture_output=True,
                        text=True).stdout.strip() if torch_ok else ""
    print(f"ready: {py}, Python {ver}; " + (f"torch {tv}" if torch_ok else "no torch, so the .pt ranker and the ensemble "
          "of shard models are off on this machine, while retrieval and phi_model check run")
          + f"; ezexe/phi {'editable from ' + str(src) if editable else 'from ' + src}")
    print(f"  {py} -m phi_model check --project {ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

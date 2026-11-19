"""What every test of this repository runs in.

pytest runs the tests on worker processes that pytest-xdist starts, or in its own process with `-n 0`. Before a
process that runs tests imports a test file, it gets:

  - a temp folder of its own, which is its working folder too, named as the file system holds it and with no
    repository above it,
  - a home folder of its own and, on Windows, app data folders of its own,
  - git settings of its own, so git reads nothing of the caller's, and
  - none of the caller's variables whose names start with a prefix in STRIP, but for those in KEEP.

So a test run from a Claude Code session sees none of that session's ids, no API key and no GitHub token, every P4_
switch is off, a live test skips, and a run spends nothing. The variables of KEEP only point a test at fixtures on
the machine, or at the folder its caller chose for the fixtures a test makes, as P4_PHI_TEST_TMP does for
test_phi.py. After each test, what it left changed in os.environ, the working folder, sys.path, tempfile.tempdir or
the temp folder is put back, so a test file runs beside any other in one process and in any order.

A file that tests the code of a plugin sits in the folder of tests/ named after that plugin and reaches that code by
its SRC folder. A hooks module's `*.test.ts` file stays inside its plugin, where `claude plugin test` reads it.
"""
import os
import shutil
import stat
import sys
import tempfile

import pytest

STRIP = ("CLAUDE", "ANTHROPIC", "P4_", "GH_TOKEN", "GITHUB_TOKEN")
KEEP = ("P4_FIXTURES", "P4_MAC_STORE", "P4_PHI_TEST_TMP")
WORKERS_MOST = 8        # half the logical processors of ezexe's machine, so a second run there has the other half
GIT_SETTINGS = "[core]\n\tautocrlf = false\n\tlongpaths = true\n[user]\n\tname = tests\n\temail = tests@localhost\n"
TEMP = None             # this process's own temp folder, once it is one that runs tests


def remove(path):
    """Remove a file or a tree, read-only files included, as git leaves its objects on Windows."""
    def again(function, name, _error):
        try:
            os.chmod(name, stat.S_IWRITE)
            function(name)
        except OSError:
            pass
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, **({"onexc": again} if sys.version_info >= (3, 12) else {"onerror": again}))
    else:
        try:
            os.remove(path)
        except OSError as e:
            again(os.remove, path, e)


def is_the_callers(name):
    """True for a variable no test is to see: its name starts with a prefix in STRIP and is not one of KEEP."""
    return name.upper().startswith(STRIP) and name.upper() not in KEEP


def isolate(base, name):
    """Give this process the folders and the environment the module's docstring names, under `base`/`name`."""
    global TEMP
    folder = os.path.join(base, name)
    tmp, home = os.path.join(folder, "t"), os.path.join(folder, "h")
    for k in [k for k in os.environ if is_the_callers(k)]:
        del os.environ[k]
    os.environ.update(TEMP=tmp, TMP=tmp, TMPDIR=tmp, HOME=home, GIT_CEILING_DIRECTORIES=base,
                      GIT_CONFIG_GLOBAL=os.path.join(home, ".gitconfig"), GIT_CONFIG_NOSYSTEM="1")
    made = [tmp, home]
    if os.name == "nt":
        os.environ.update(USERPROFILE=home, APPDATA=os.path.join(home, "AppData", "Roaming"),
                          LOCALAPPDATA=os.path.join(home, "AppData", "Local"))
        made += [os.environ["APPDATA"], os.environ["LOCALAPPDATA"]]
    for d in made:
        os.makedirs(d, exist_ok=True)
    with open(os.environ["GIT_CONFIG_GLOBAL"], "w", encoding="utf-8", newline="\n") as f:
        f.write(GIT_SETTINGS)
    tempfile.tempdir = None             # read from TMPDIR again
    os.chdir(tmp)
    TEMP = tmp


def pytest_configure(config):
    worker = getattr(config, "workerinput", None)
    if worker is not None:              # a worker pytest-xdist started
        isolate(worker["p4_base"], worker["workerid"])
        return
    # Named as the file system holds it, with no 8.3 short name of Windows and no link above it: a GitHub runner's
    # TEMP is C:\Users\RUNNER~1\AppData\Local\Temp, and git and os.path.realpath name a folder under it in full.
    config.p4_base = os.path.realpath(tempfile.mkdtemp(prefix="p4-tests-"))
    if not config.getoption("numprocesses", None):      # no workers: this process runs the tests
        config.p4_cwd = os.getcwd()
        isolate(config.p4_base, "main")


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node):
    """pytest-xdist calls this in the process that started it, once for each worker: hand the worker its folder."""
    node.workerinput["p4_base"] = node.config.p4_base


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_auto_num_workers(config):
    """What `-n auto` means here: a worker for each logical processor, WORKERS_MOST at most."""
    return max(1, min(WORKERS_MOST, os.cpu_count() or 1))


def pytest_unconfigure(config):
    base = getattr(config, "p4_base", None)
    if base:
        if getattr(config, "p4_cwd", None):
            os.chdir(config.p4_cwd)
        try:
            remove(base)
        except OSError:
            pass                        # a process a test started may still hold a file in it


@pytest.fixture(autouse=True)
def put_back():
    """After each test, put back what it left changed, and remove what it left in the temp folder."""
    environ, cwd, path, tempdir = dict(os.environ), os.getcwd(), list(sys.path), tempfile.tempdir
    had = set(os.listdir(TEMP))
    yield
    os.environ.clear()
    os.environ.update(environ)
    try:
        os.chdir(cwd)
    except OSError:
        os.chdir(TEMP)
    sys.path[:] = path
    tempfile.tempdir = tempdir
    for name in set(os.listdir(TEMP)) - had:
        try:
            remove(os.path.join(TEMP, name))
        except OSError:
            pass                        # a process the test left running may still hold it

"""run.py: the one command that runs every test of this repository and prints each test's duration.

    python -X utf8 suite/run.py                          every test, checked against the budget suite.json names
    python -X utf8 suite/run.py <file, folder or id>...  only those, with no budget check
    python -X utf8 suite/run.py --files                  each test file and how the command loads it, running nothing
    python -X utf8 suite/run.py --tsv <path> --label <words>   also appends one row a test to that TSV file

The command takes every file of the repository named test_*.py that git tracks, or holds untracked and not ignored,
and runs its tests on worker processes, as many as suite.json names. A worker imports one file at a time and runs its
tests, and once every file is taken an idle worker takes tests from the end of the file with the most left, one it has
imported first, so a long file is shared out test by test. The command prints one line a test with its seconds, its outcome and its id, then each
failure, the state tests left behind, the slowest tests, the seconds of each part, the totals and the budget's verdict.
A test's id is its file, class and method, as `lbiza/plugins/p4-phi/scripts/test_phi.py::Hooks::test_x`, and a file
run whole is its path alone.

What a test file must be for the command to load it:

  1. Named test_*.py. A test file that another one imports by name, as test_plans.py imports test_phi.py, has a name
     no other test file has, and a module that two folders of tests both hold, as p4conf.py, is the same file in
     each, since a worker imports each name once. A worker that holds a module of another folder by the name of one
     in this file's folder, with other contents, fails this file.
  2. Its tests are unittest.TestCase classes it defines, or functions named test_* that take no argument. A file with
     neither and an `if __name__ == "__main__":` block runs whole as one test in a process of its own and passes when
     it exits 0, which costs a process and shares nothing out. Any other file named test_*.py fails the run.
  3. It needs only the standard library and this repository, on the python that runs the command.
  4. It runs beside any other test file in one worker and in any order. What it sets in os.environ, the working folder
     or sys.path when the command imports it stays for that worker. What a test or a class leaves changed in them, in
     tempfile.tempdir or in the temp folder, the command puts back and names in its report, an import a test makes
     itself included.
  5. It needs nothing of the caller's: each worker has a temp folder, a home folder and app data folders of its own
     and empty, the temp folder has no repository above it and is the working folder, and every variable whose name
     starts with a prefix suite.json lists is removed, so a live test behind a P4_ switch skips and a run spends
     nothing.
  6. Each test ends within the timeout suite.json names, or its worker is stopped, the test fails, and another worker
     takes the tests left.

Exit status: 0 when every test passed and the run ended within the budget, 1 when a test failed, raised an error or
timed out or a file could not be loaded, 3 when every test passed and the run took longer than the budget, and 2 for a
bad command line. With a file, folder or test named, the budget is not checked.
"""
import argparse
import collections
import faulthandler
import fnmatch
import io
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest

T0 = time.perf_counter()
HERE = os.path.dirname(os.path.abspath(__file__))
DEFINITION = os.path.join(HERE, "suite.json")
OK, FAILED, USAGE, OVER_BUDGET = 0, 1, 2, 3
UNIT = re.compile(r"^(?:import[ \t][^\n]*\bunittest\b|from[ \t]+unittest\b|def[ \t]+test_\w*[ \t]*\()", re.M)
MAIN = re.compile(r"""^if[ \t]+__name__[ \t]*==[ \t]*["']__main__["'][ \t]*:""", re.M)
PASSING = ("ok", "skip")
WORST = {"ok": 0, "skip": 1, "FAIL": 2, "ERROR": 3, "TIMEOUT": 4}
TSV_RESULT = {"ok": "PASSED", "skip": "SKIPPED", "FAIL": "FAILED", "ERROR": "ERROR", "TIMEOUT": "TIMEOUT"}
START_S = 60.0          # a worker that has not connected by then is taken as failed to start
END_S = 60.0            # a worker that has not answered "end" by then is stopped


# --- the suite's definition and its files --------------------------------------------------------------------------

def definition(path=DEFINITION):
    """The settings the command reads from suite.json: the budget, the workers, the timeout, the file pattern and the
    prefixes of the variables removed from each worker's environment."""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return {"budget": float(d["budget"]["seconds"]), "workers": int(d["workers"]["count"]),
            "timeout": float(d["timeout"]["seconds"]), "pattern": d["files"]["pattern"],
            "strip": [str(p) for p in d["environment"]["strip"]]}


def test_files(root, pattern="test_*.py"):
    """Every file of `root` whose name matches `pattern`, as a path relative to it with forward slashes, sorted. In a
    git checkout these are the files git tracks, or holds untracked and not ignored; anywhere else, every file outside
    folders whose names start with a dot."""
    names = None
    if os.path.exists(os.path.join(root, ".git")):
        r = subprocess.run(["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                           capture_output=True)
        if r.returncode == 0:
            names = [n.decode("utf-8", "replace") for n in r.stdout.split(b"\0") if n]
    if names is None:
        names = []
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if not x.startswith(".") and x != "__pycache__"]
            names += [os.path.relpath(os.path.join(d, f), root) for f in files]
    found = {n.replace("\\", "/") for n in names}
    return sorted(n for n in found if fnmatch.fnmatchcase(n.rsplit("/", 1)[-1], pattern)
                  and os.path.isfile(os.path.join(root, n)))


def kind_of(path):
    """How the command loads a test file: "unit" for unittest classes or test_ functions, run test by test; "script"
    for a file with neither and a __main__ block, run whole in a process of its own; "none" for any other file."""
    with open(path, encoding="utf-8", errors="replace") as f:
        src = f.read()
    if UNIT.search(src):
        return "unit"
    if MAIN.search(src):
        return "script"
    return "none"


def part_of(rel):
    """The part of the repository a test belongs to: a plugin's folder, or the top folder."""
    bits = rel.split("/")
    return "/".join(bits[:3]) if bits[:2] == ["lbiza", "plugins"] and len(bits) > 3 else bits[0]


def repository_above(path):
    """The first folder at or above `path` that holds a .git, or None."""
    p = os.path.abspath(path)
    while True:
        if os.path.exists(os.path.join(p, ".git")):
            return p
        q = os.path.dirname(p)
        if q == p:
            return None
        p = q


def worker_env(base, folder, strip, ceiling, real_home, windows=(os.name == "nt")):
    """The environment of one worker: `base` without the variables whose names start with a prefix in `strip`, with a
    temp folder and a home folder of its own under `folder`, and git kept from looking for a repository above
    `ceiling`. On Windows python finds the home folder through USERPROFILE and git through HOME, so HOME stays the
    real one and git keeps its global settings; elsewhere both read HOME, so git is pointed at the real global file."""
    prefixes = tuple(p.upper() for p in strip)
    env = {k: v for k, v in base.items() if not k.upper().startswith(prefixes)}
    tmp, home = os.path.join(folder, "t"), os.path.join(folder, "h")
    env.update(TEMP=tmp, TMP=tmp, TMPDIR=tmp, GIT_CEILING_DIRECTORIES=ceiling)
    made = [tmp, home]
    if windows:
        env.update(USERPROFILE=home, APPDATA=os.path.join(home, "AppData", "Roaming"),
                   LOCALAPPDATA=os.path.join(home, "AppData", "Local"))
        env.setdefault("HOME", real_home)
        made += [env["APPDATA"], env["LOCALAPPDATA"]]
    else:
        env["HOME"] = home
        xdg = base.get("XDG_CONFIG_HOME") or os.path.join(real_home, ".config")
        for cfg in (os.path.join(real_home, ".gitconfig"), os.path.join(xdg, "git", "config")):
            if os.path.isfile(cfg):
                env.setdefault("GIT_CONFIG_GLOBAL", cfg)
                break
    for d in made:
        os.makedirs(d, exist_ok=True)
    return env


def remove(path):
    """Remove a file or a tree, read-only files included, as git leaves its objects on Windows; True when it is gone."""
    def writable(fn, p, *_):
        try:
            os.chmod(p, 0o700)
            fn(p)
        except OSError:
            pass
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            if sys.version_info >= (3, 12):
                shutil.rmtree(path, onexc=writable)
            else:
                shutil.rmtree(path, onerror=writable)
        else:
            os.chmod(path, 0o700)
            os.remove(path)
    except OSError:
        pass
    return not os.path.lexists(path)


def kill_tree(proc):
    """Stop a worker and every process it started."""
    if proc.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            import signal
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        pass


def same_path(a, b):
    return bool(a) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def foreign(folder):
    """The modules `folder` holds that this process has imported from another file with other contents. A process
    imports each name once, so a test of this folder would run against that other file."""
    import filecmp
    out = []
    for f in sorted(os.listdir(folder)):
        if f.endswith(".py") and not f.startswith("test_"):
            at = getattr(sys.modules.get(f[:-3]), "__file__", None)
            mine = os.path.join(folder, f)
            if at and not same_path(at, mine) and not filecmp.cmp(at, mine, shallow=False):
                out.append(f"{f[:-3]} is {at}")
    return out


def tail(text, n=4000):
    text = text or ""
    return text if len(text) <= n else "...\n" + text[-n:]


# --- a worker: imports test files and runs their tests one at a time ------------------------------------------------

class State:
    """What a test may change and must put back: os.environ, the working folder, sys.path, tempfile.tempdir and the
    entries of the worker's temp folder."""

    def __init__(self, tmp):
        self.tmp = tmp
        self.env = dict(os.environ)
        self.cwd = os.getcwd()
        self.path = list(sys.path)
        self.tempdir = tempfile.tempdir
        self.entries = set(os.listdir(tmp))

    def restore(self):
        """Put back what changed since this state was taken, and say what it was."""
        said = []
        now = dict(os.environ)
        if now != self.env:
            added = sorted(set(now) - set(self.env))
            gone = sorted(set(self.env) - set(now))
            changed = sorted(k for k in set(now) & set(self.env) if now[k] != self.env[k])
            words = [f"set {', '.join(added)}"] * bool(added) + [f"removed {', '.join(gone)}"] * bool(gone) + \
                    [f"changed {', '.join(changed)}"] * bool(changed)
            said.append("os.environ: " + "; ".join(words))
            for k in added:
                del os.environ[k]
            for k in gone + changed:
                os.environ[k] = self.env[k]
        try:
            cwd = os.getcwd()
        except OSError:
            cwd = None
        if cwd != self.cwd:
            said.append("the working folder")
            os.chdir(self.cwd)
        if sys.path != self.path:
            said.append("sys.path")
            sys.path[:] = self.path
        if tempfile.tempdir != self.tempdir:
            said.append("tempfile.tempdir")
            tempfile.tempdir = self.tempdir
        try:
            left = sorted(set(os.listdir(self.tmp)) - self.entries)
        except OSError:
            left = []
        if left:
            kept = [n for n in left if not remove(os.path.join(self.tmp, n))]
            self.entries.update(kept)
            more = f" and {len(left) - 5} more" if len(left) > 5 else ""
            said.append("left in the temp folder: " + ", ".join(left[:5]) + more +
                        (f"; {len(kept)} could not be removed" if kept else ""))
        return said


class Runner:
    """One worker's tests: the files it imported, the class whose fixture is up, and the result they report to."""

    def __init__(self, root, timeout):
        self.root, self.timeout = root, timeout
        self.tmp = tempfile.gettempdir()
        os.chdir(self.tmp)
        self.loader = unittest.TestLoader()
        self.suite = unittest.TestSuite()
        self.result = Result()
        self.tests = {}            # test id -> test
        self.loaded = {}           # file -> None once imported, or the error that stopped it
        self.modules = {}          # module name -> file
        self.cls = None            # the class whose setUpClass ran last and whose tearDownClass has not
        self.cls_id = None
        self.failed_setup = None   # `outcome, text` when that class or its module could not be set up
        self.entry = self.inside = None

    def load(self, rel):
        """Import a test file from its own path and take its tests; the error when it cannot be. It is imported by its
        own name, as the test files that import it name it, unless another test file of that name is already here."""
        if rel in self.loaded:
            return self.loaded[rel]
        import importlib.util
        import types
        path = os.path.normpath(os.path.join(self.root, rel))
        folder, name = os.path.dirname(path), os.path.basename(path)[:-3]
        try:
            if os.path.normcase(folder) not in (os.path.normcase(p) for p in sys.path):
                sys.path.insert(0, folder)
            mod = sys.modules.get(name)
            if mod is None or not same_path(getattr(mod, "__file__", None), path):
                if mod is not None:
                    name = name + "__" + re.sub(r"\W", "_", os.path.dirname(rel))
                spec = importlib.util.spec_from_file_location(name, path)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[name] = mod
                try:
                    spec.loader.exec_module(mod)
                except BaseException:
                    sys.modules.pop(name, None)
                    raise
            mixed = foreign(folder)
            if mixed:
                raise ImportError("this worker holds a module of this file's folder from another folder, with other "
                                  "contents: " + "; ".join(mixed))
            for attr, obj in vars(mod).items():
                if isinstance(obj, type) and issubclass(obj, unittest.TestCase) and obj.__module__ == name:
                    for t in self.loader.loadTestsFromTestCase(obj):
                        self.tests[f"{rel}::{obj.__qualname__}::{t._testMethodName}"] = t
                elif (isinstance(obj, types.FunctionType) and attr.startswith("test_")
                      and obj.__module__ == name):
                    self.tests[f"{rel}::{attr}"] = unittest.FunctionTestCase(obj)
            self.modules[name] = rel
            self.loaded[rel] = None
        except KeyboardInterrupt:
            raise
        except BaseException:
            self.loaded[rel] = traceback.format_exc()
        return self.loaded[rel]

    def collect(self, rel):
        """Import a file and name its tests. The class whose fixture is up is torn down first, so what the import sets
        stays for the worker and is not taken for something that class left."""
        leaks, extra = [], []
        self.close_class(leaks, extra)
        t = time.perf_counter()
        err = self.load(rel)
        ids = [] if err else [i for i in self.tests if i.split("::", 1)[0] == rel]
        return ("collected", rel, ids, err, time.perf_counter() - t, leaks, extra)

    def guard(self, fn, *args):
        """Call a fixture step of unittest, which lets SystemExit and the like through, as a test call would not."""
        try:
            fn(*args)
        except KeyboardInterrupt:
            raise
        except BaseException:
            self.result.events.append((None, "ERROR", f"{fn.__name__}: " + traceback.format_exc()))

    def fixture_rows(self, events):
        """Rows for the errors a class or module fixture reported, under the id of the class or module."""
        rows = []
        for t, outcome, text in events:
            desc = getattr(t, "description", "") or ""
            m = re.match(r"(\w+) \(([\w.]+)\)", desc)
            uid = desc or "<fixture>"
            if m:
                mod, _, cls = m.group(2).partition(".")
                rel = self.modules.get(mod, mod)
                uid = "::".join(x for x in (rel, cls, m.group(1)) if x)
            rows.append((uid, outcome, 0.0, text))
        return rows

    def close_class(self, leaks, extra):
        """Tear down the class whose fixture is up, and put back what it left."""
        if self.cls is None:
            return
        n = len(self.result.events)
        self.guard(self.suite._tearDownPreviousClass, None, self.result)
        extra += self.fixture_rows(self.result.events[n:])
        leaks += [(self.cls_id, s) for s in self.entry.restore()]
        # a stand-in that keeps the module, for unittest's module fixtures, and is no class a test belongs to
        self.result._previousTestClass = type("Closed", (), {"__module__": self.cls.__module__})
        self.cls = self.failed_setup = None

    def run(self, uid):
        leaks, extra = [], []
        rel = uid.split("::", 1)[0]
        if rel not in self.loaded:
            self.close_class(leaks, extra)
            self.load(rel)
        test = self.tests.pop(uid, None)
        if test is None:
            return ("done", uid, "ERROR", 0.0, self.loaded.get(rel) or "no such test", leaks, extra)
        t0 = time.perf_counter()
        cls = type(test)
        if cls is not self.cls:
            self.close_class(leaks, extra)
            n = len(self.result.events)
            self.guard(self.suite._handleModuleFixture, test, self.result)
            module = self.result.events[n:]
            # a module change tears the last module down here too: its errors are that module's, not this class's
            ended = [e for e in module if getattr(e[0], "description", "").startswith("tearDownModule")]
            extra += self.fixture_rows(ended)
            setup = [e for e in module if e not in ended]
            self.entry = State(self.tmp)
            n = len(self.result.events)
            self.guard(self.suite._handleClassSetUp, test, self.result)
            setup += self.result.events[n:]
            self.result._previousTestClass = cls
            self.cls, self.cls_id = cls, uid.rsplit("::", 1)[0]
            if (setup or getattr(cls, "_classSetupFailed", False)
                    or getattr(self.result, "_moduleSetUpFailed", False)):
                worst = max(setup, key=lambda e: WORST[e[1]]) if setup else (None, "ERROR", "setUpClass failed")
                self.failed_setup = (worst[1], worst[2])
            self.inside = State(self.tmp)
        if self.failed_setup:
            outcome, text = self.failed_setup
            return ("done", uid, outcome, time.perf_counter() - t0, text, leaks, extra)
        n = len(self.result.events)
        out = io.BytesIO()
        stream = io.TextIOWrapper(out, encoding="utf-8", errors="replace", write_through=True)
        saved = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = stream
        self.watch(True)
        try:
            test(self.result)
        except KeyboardInterrupt:
            raise
        except BaseException:
            self.result.events.append((test, "ERROR", traceback.format_exc()))
        finally:
            self.watch(False)
            sys.stdout, sys.stderr = saved
        seconds = time.perf_counter() - t0
        leaks += [(uid, s) for s in self.inside.restore()]
        outcome, text = self.outcome(self.result.events[n:])
        printed = out.getvalue().decode("utf-8", "replace")
        if outcome not in PASSING and printed.strip():
            text += "\n--- printed ---\n" + tail(printed)
        return ("done", uid, outcome, seconds, text, leaks, extra)

    def watch(self, on):
        """Write every thread's stack to the worker's log shortly before the command would stop a hung test."""
        if on:
            faulthandler.dump_traceback_later(max(self.timeout - min(5.0, self.timeout / 4), 0.1), file=sys.__stderr__)
        else:
            faulthandler.cancel_dump_traceback_later()

    @staticmethod
    def outcome(events):
        """One outcome for the events a test reported: the worst of them, with their texts."""
        if not events:
            return "ERROR", "the test reported no outcome"
        worst = max((e[1] for e in events), key=WORST.get)
        return worst, "\n".join(e[2] for e in events if e[1] == worst and e[2])

    def script(self, rel):
        """A test file with no unittest tests and a __main__ block, run whole as its own process."""
        path = os.path.normpath(os.path.join(self.root, rel))
        before = State(self.tmp)
        t0 = time.perf_counter()
        try:
            p = subprocess.run([sys.executable, "-X", "utf8", path], cwd=os.path.dirname(path), capture_output=True,
                               stdin=subprocess.DEVNULL, timeout=max(self.timeout * 0.95, 0.5))
            printed = (p.stdout + p.stderr).decode("utf-8", "replace")
            outcome = "ok" if p.returncode == 0 else "FAIL"
            text = "" if p.returncode == 0 else f"exit code {p.returncode}\n--- printed ---\n{tail(printed)}"
        except subprocess.TimeoutExpired as e:
            printed = ((e.stdout or b"") + (e.stderr or b"")).decode("utf-8", "replace")
            outcome, text = "TIMEOUT", f"still running after {e.timeout:.0f} s\n--- printed ---\n{tail(printed)}"
        seconds = time.perf_counter() - t0
        return ("done", rel, outcome, seconds, text, [(rel, s) for s in before.restore()], [])

    def end(self):
        leaks, extra = [], []
        self.close_class(leaks, extra)
        n = len(self.result.events)
        self.guard(self.suite._handleModuleTearDown, self.result)
        extra += self.fixture_rows(self.result.events[n:])
        return ("ended", extra, leaks)


class Result(unittest.TestResult):
    """Each outcome a test reports, as `test, outcome, text`, in the order reported."""

    def __init__(self):
        super().__init__()
        self.events = []

    def text(self, test, err):
        if test is not None and hasattr(test, "failureException"):
            return self._exc_info_to_string(err, test)
        return "".join(traceback.format_exception(*err))

    def addSuccess(self, test):
        self.events.append((test, "ok", ""))

    def addError(self, test, err):
        self.events.append((test, "ERROR", self.text(test, err)))

    def addFailure(self, test, err):
        self.events.append((test, "FAIL", self.text(test, err)))

    def addSkip(self, test, reason):
        self.events.append((test, "skip", reason))

    def addExpectedFailure(self, test, err):
        self.events.append((test, "ok", "failed as expected"))

    def addUnexpectedSuccess(self, test):
        self.events.append((test, "FAIL", "passed, though it is marked as expected to fail"))

    def addSubTest(self, test, subtest, err):
        if err is not None:
            outcome = "FAIL" if issubclass(err[0], test.failureException) else "ERROR"
            self.events.append((test, outcome, f"{subtest._subDescription()}\n{self.text(test, err)}"))


def worker(a):
    from multiprocessing.connection import Client
    conn = Client(a.connect, authkey=bytes.fromhex(a.key))
    conn.send(("hello", a.worker))
    runner = Runner(a.root, a.timeout)
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return FAILED
        if msg[0] == "end":
            conn.send(runner.end())
            break
        conn.send(getattr(runner, msg[0])(msg[1]))
    conn.close()
    # the command removes the worker's folders itself, so nothing a test registered for the exit is waited on: a
    # thread a test left running would otherwise hold the worker open
    os._exit(OK)


# --- the command: discovery, the workers, the report ----------------------------------------------------------------

Row = collections.namedtuple("Row", "id file test outcome seconds text worker")


class Worker:
    def __init__(self, k, proc, folder, log):
        self.k, self.proc, self.folder, self.log = k, proc, folder, log
        self.conn = None
        self.job = None            # `kind, name` while the worker has a job: collect, run, script or end
        self.since = self.started = time.perf_counter()
        self.affinity = None       # the file whose tests it takes first
        self.steal = False         # whether it takes them from the end of that file's queue
        self.loaded = set()
        self.ended = False


class Run:
    def __init__(self, root, d, workers, only):
        self.root, self.d, self.only = root, d, only
        self.n = max(1, min(workers, os.cpu_count() or 1))
        self.timeout = d["timeout"]
        self.rows, self.leaks = {}, []
        self.queues = {}           # file -> deque of the test ids not yet given out
        self.collecting = set()
        self.uncollected = collections.deque()
        self.scripts = collections.deque()
        self.workers, self.by_conn, self.by_k = [], {}, {}
        self.spawned = 0
        self.import_s = 0.0
        self.accepted = queue.Queue()
        self.closing = False
        self.used = set()

    # what to run

    def wanted(self, uid):
        if not self.only:
            return True
        hit = [s for s in self.only if not s or uid == s or uid.startswith(s + "::")
               or uid.startswith(s.rstrip("/") + "/")]
        self.used.update(hit)
        return bool(hit)

    def plan(self, files):
        """Scripts first, each one long and whole; then the unittest files, the largest first."""
        units = []
        for rel in files:
            if not self.wanted(rel) and not any(s.split("::", 1)[0] == rel for s in self.only):
                continue
            kind = kind_of(os.path.join(self.root, rel))
            if kind == "script":
                self.scripts.append(rel)
            elif kind == "unit":
                units.append(rel)
            else:
                self.row(rel, "ERROR", 0.0, "a file named test_*.py with no unittest test, no test_ function and no "
                                            "__main__ block", None)
        units.sort(key=lambda r: -os.path.getsize(os.path.join(self.root, r)))
        self.uncollected.extend(units)

    def row(self, uid, outcome, seconds, text, w):
        rel, _, test = uid.partition("::")
        self.rows[uid] = Row(uid, rel, test or "<file>", outcome, seconds, text or "", w.k if w else None)

    # the workers

    def start(self):
        from multiprocessing.connection import Listener
        self.key = os.urandom(16)
        self.listener = Listener(authkey=self.key)
        threading.Thread(target=self.accept, daemon=True).start()
        for _ in range(self.n):
            self.spawn()

    def accept(self):
        while not self.closing:
            try:
                c = self.listener.accept()
            except Exception:
                if self.closing:
                    return
                time.sleep(0.05)
                continue
            try:
                hello = c.recv()
                self.accepted.put((hello[1], c))
            except Exception:
                c.close()

    def spawn(self):
        k = self.spawned
        self.spawned += 1
        folder = os.path.join(self.base, str(k))
        env = worker_env(os.environ, folder, self.d["strip"], self.base, self.real_home)
        log = open(os.path.join(folder, "log"), "wb")
        cmd = [sys.executable, "-X", "utf8", "-u", os.path.abspath(__file__), "--worker", str(k), "--connect",
               self.listener.address, "--key", self.key.hex(), "--root", self.root, "--timeout", str(self.timeout)]
        extra = {"start_new_session": True} if os.name != "nt" else {}
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env,
                                cwd=env["TEMP"], **extra)
        w = Worker(k, proc, folder, log)
        self.workers.append(w)
        self.by_k[k] = w
        return w

    def log_of(self, w):
        try:
            w.log.flush()
            with open(os.path.join(w.folder, "log"), encoding="utf-8", errors="replace") as f:
                return tail(f.read(), 3000)
        except OSError:
            return ""

    def send(self, w, msg):
        w.job, w.since = (msg[0], msg[1] if len(msg) > 1 else None), time.perf_counter()
        try:
            w.conn.send(msg)
        except (OSError, EOFError, ValueError):
            self.lost(w, "its connection broke")

    def give(self, w):
        q = self.queues.get(w.affinity)
        if q:
            return self.send(w, ("run", q.pop() if w.steal else q.popleft()))
        if self.scripts:
            return self.send(w, ("script", self.scripts.popleft()))
        if self.uncollected:
            rel = self.uncollected.popleft()
            self.collecting.add(rel)
            w.affinity, w.steal = rel, False
            return self.send(w, ("collect", rel))
        left = [(r in w.loaded, len(q), r) for r, q in self.queues.items() if q]
        if left:
            r = max(left)[2]
            w.affinity, w.steal = r, True
            return self.send(w, ("run", self.queues[r].pop()))
        if not self.collecting:
            self.send(w, ("end",))

    def work_left(self):
        return bool(self.scripts or self.uncollected or self.collecting or any(self.queues.values()))

    def lost(self, w, why, outcome="ERROR"):
        """A worker that died, hung or never started: its job fails, and another takes its place while work is left."""
        if w.ended:
            return
        w.ended = True
        kill_tree(w.proc)
        if w.conn is not None:
            self.by_conn.pop(w.conn, None)
            try:
                w.conn.close()
            except OSError:
                pass
        text = f"worker {w.k} {why}\n--- its log ---\n{self.log_of(w)}"
        kind, name = w.job or (None, None)
        seconds = time.perf_counter() - w.since
        if kind == "run" or kind == "script":
            self.row(name, outcome, seconds, text, w)
        elif kind == "collect":
            self.collecting.discard(name)
            self.row(name + "::<import>", outcome, seconds, text, w)
        elif kind is None and w.conn is None:
            self.row(f"<worker {w.k}>", "ERROR", seconds, text, w)
        w.job = None
        if self.work_left() and self.spawned < 2 * self.n + 2:
            self.spawn()

    def handle(self, w, msg):
        kind = msg[0]
        if kind == "collected":
            _, rel, ids, err, seconds, leaks, extra = msg
            for x in extra:
                self.row(*x, w)
            self.leaks += leaks
            self.collecting.discard(rel)
            self.import_s += seconds
            w.loaded.add(rel)
            if err:
                self.row(rel + "::<import>", "ERROR", seconds, err, w)
            else:
                mine = [i for i in ids if self.wanted(i)]
                if not ids:
                    self.row(rel + "::<no tests>", "ERROR", 0.0, "the file defines no test the command can load", w)
                self.queues[rel] = collections.deque(mine)
        elif kind == "done":
            _, uid, outcome, seconds, text, leaks, extra = msg
            self.row(uid, outcome, seconds, text, w)
            for x in extra:
                self.row(*x, w)
            self.leaks += leaks
        elif kind == "ended":
            _, extra, leaks = msg
            for x in extra:
                self.row(*x, w)
            self.leaks += leaks
            w.ended = True
            self.by_conn.pop(w.conn, None)
        w.job = None

    def loop(self):
        from multiprocessing.connection import wait
        while True:
            while True:
                try:
                    k, c = self.accepted.get_nowait()
                except queue.Empty:
                    break
                w = self.by_k.get(k)
                if w is None or w.conn is not None or w.ended:
                    c.close()
                    continue
                w.conn = c
                self.by_conn[c] = w
            live = list(self.by_conn)
            ready = wait(live, timeout=0.2) if live else []
            if not live:
                time.sleep(0.02)
            for c in ready:
                w = self.by_conn.get(c)
                if w is None:
                    continue
                try:
                    msg = c.recv()
                except (EOFError, OSError):
                    self.lost(w, "closed its connection")
                    continue
                self.handle(w, msg)
            now = time.perf_counter()
            for w in list(self.workers):
                if w.ended:
                    continue
                rc = w.proc.poll()
                if rc is not None:
                    try:
                        while w.conn is not None and not w.ended and w.conn.poll(0):
                            self.handle(w, w.conn.recv())
                    except (EOFError, OSError):
                        pass
                    if not w.ended:
                        self.lost(w, f"exited with code {rc}")
                elif w.conn is None and now - w.started > START_S:
                    self.lost(w, f"did not connect within {START_S:.0f} s")
                elif w.job and w.job[0] == "end" and now - w.since > END_S:
                    self.lost(w, f"did not end within {END_S:.0f} s")
                elif w.job and w.job[0] != "end" and now - w.since > self.timeout:
                    self.lost(w, f"was stopped after {self.timeout:.0f} s on this test", "TIMEOUT")
            for w in self.workers:
                if w.conn is not None and not w.ended and w.job is None:
                    self.give(w)
            if all(w.ended for w in self.workers):
                if self.work_left():
                    self.row("<suite>::<workers>", "ERROR", 0.0, "no worker is left to run the tests not yet run: " +
                             ", ".join(sorted(set(self.scripts) | set(self.uncollected) |
                                              {r for r, q in self.queues.items() if q})), None)
                return

    def stop(self):
        self.closing = True
        try:
            from multiprocessing.connection import Client
            Client(self.listener.address, authkey=self.key).close()
        except Exception:
            pass
        try:
            self.listener.close()
        except Exception:
            pass
        for w in self.workers:
            try:
                w.proc.wait(5 if w.ended else 0)
            except subprocess.TimeoutExpired:
                pass
            kill_tree(w.proc)
            w.log.close()
            if w.conn is not None:
                try:
                    w.conn.close()
                except OSError:
                    pass


def many(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def report(rows, leaks, workers, wall, import_s, budget, source="suite/suite.json", quiet=False):
    """The lines the command prints, and its exit status. `budget` is None when only some tests ran."""
    rows = sorted(rows, key=lambda r: r.id)
    lines = [] if quiet else [f"{r.seconds:8.3f} s  {r.outcome:<7} {r.id}" for r in rows]
    bad = [r for r in rows if r.outcome not in PASSING]
    for r in bad:
        lines += ["", f"=== {r.outcome} {r.id}" + (f" on worker {r.worker}" if r.worker is not None else ""),
                  r.text.rstrip()]
    if leaks:
        by = collections.OrderedDict()
        for uid, s in leaks:
            by.setdefault(uid, []).append(s)
        who = "test or class" if len(by) == 1 else "tests or classes"
        lines += ["", f"what {len(by)} {who} left changed, which the command put back:"]
        lines += [f"  {uid}: " + "; ".join(said) for uid, said in by.items()]
    total = sum(r.seconds for r in rows)
    longest = max((r.seconds for r in rows), default=0.0)
    if rows:
        lines += ["", "slowest:"] + [f"{r.seconds:8.3f} s  {r.id}" for r in sorted(rows, key=lambda r: -r.seconds)[:10]]
        parts = collections.OrderedDict()
        for r in rows:
            p = parts.setdefault(part_of(r.file), [0, 0.0])
            p[0] += 1
            p[1] += r.seconds
        lines += ["", "by part:"] + [f"{s:8.1f} s  {many(n, 'test'):>11}  {p}" for p, (n, s) in sorted(parts.items())]
    count = collections.Counter(r.outcome for r in rows)
    files = len({r.file for r in rows})
    lines += ["", f"{many(len(rows), 'test')} in {many(files, 'file')} on {many(workers, 'worker')}: "
                  f"{count['ok']} passed, {count['FAIL']} failed, {many(count['ERROR'], 'error')}, "
                  f"{count['TIMEOUT']} timed out, {count['skip']} skipped",
              f"test time {total:.1f} s, imports {import_s:.1f} s, wall {wall:.1f} s",
              f"lower bound for these tests on {many(workers, 'worker')}: "
              f"{max(longest, total / max(workers, 1)):.1f} s, the longest test {longest:.1f} s"]
    status = FAILED if bad or not rows else OK
    if budget is None:
        lines.append("budget: not checked, since only some tests ran")
    elif wall <= budget:
        lines.append(f"budget {budget:g} s from {source}: within it by {budget - wall:.1f} s")
    else:
        lines.append(f"budget {budget:g} s from {source}: passed by {wall - budget:.1f} s")
        status = status or OVER_BUDGET
    return lines, status


def write_tsv(path, label, rows, wall, workers, status):
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        if new:
            f.write("label\tfile\ttest\tseconds\tresult\n")
        for r in sorted(rows, key=lambda r: r.id):
            f.write(f"{label}\t{r.file}\t{r.test}\t{r.seconds:.3f}\t{TSV_RESULT.get(r.outcome, r.outcome)}\n")
        f.write(f"{label}\t<suite>\t<wall>\t{wall:.3f}\tworkers={workers} exit={status}\n")


def selectors(only, root):
    """Each file, folder or test named on the command line, as a path relative to the repository."""
    out = []
    for s in only:
        path, sep, rest = s.partition("::")
        p = path if os.path.isabs(path) else os.path.abspath(path)
        if not os.path.exists(p):
            p = os.path.join(root, path)
        try:
            rel = os.path.relpath(p, root).replace("\\", "/")
        except ValueError:
            rel = path.replace("\\", "/")
        out.append(("" if rel == "." else rel) + sep + rest)
    return out


def main(argv=None):
    t0 = T0 if argv is None else time.perf_counter()
    ap = argparse.ArgumentParser(prog="suite/run.py", description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("only", nargs="*", help="files, folders or test ids to run, with no budget check")
    ap.add_argument("--root", default=os.path.dirname(HERE), help="the repository; the folder above suite/")
    ap.add_argument("--workers", type=int, help="worker processes; suite.json names how many")
    ap.add_argument("--budget", type=float, help="seconds a whole run may take; suite.json names it")
    ap.add_argument("--timeout", type=float, help="seconds a test may take; suite.json names it")
    ap.add_argument("--files", action="store_true", help="list each test file and how it is loaded, run nothing")
    ap.add_argument("--quiet", action="store_true", help="leave out the line of each test that passed or skipped")
    ap.add_argument("--tsv", help="append one row a test to this TSV file")
    ap.add_argument("--label", default="", help="the first column of the TSV rows")
    ap.add_argument("--keep", action="store_true", help="keep the run's folder of worker temp folders and logs")
    ap.add_argument("--worker", type=int, help=argparse.SUPPRESS)
    ap.add_argument("--connect", help=argparse.SUPPRESS)
    ap.add_argument("--key", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.worker is not None:
        a.root = os.path.abspath(a.root)
        return worker(a)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    root = os.path.abspath(a.root)
    d = definition()
    if a.timeout is not None:
        d["timeout"] = a.timeout
    files = test_files(root, d["pattern"])
    if a.files:
        kinds = [(kind_of(os.path.join(root, f)), f) for f in files]
        how = {"unit": "its tests, one by one", "script": "run whole in a process of its own",
               "none": "nothing the command can load"}
        for k, f in kinds:
            print(f"{k:<7} {f}  {how[k]}")
        return FAILED if any(k == "none" for k, _ in kinds) else OK
    only = selectors(a.only, root)
    workers = a.workers or d["workers"]
    if only and all("::" in s for s in only):
        workers = min(workers, len(only))
    run = Run(root, d, workers, only)
    run.real_home = os.path.expanduser("~")
    run.base = tempfile.mkdtemp(prefix="p4s-")
    above = repository_above(os.path.dirname(run.base))
    if above:
        remove(run.base)
        print(f"suite/run.py: the temp folder {run.base} sits inside the repository {above}, where a test tree would "
              f"find it; set TEMP to a folder outside every repository", file=sys.stderr)
        return USAGE
    run.plan(files)
    print(f"suite/run.py: {many(len(run.scripts) + len(run.uncollected), 'test file')} on {many(run.n, 'worker')}",
          file=sys.stderr, flush=True)
    status = OK
    try:
        run.start()
        run.loop()
    except KeyboardInterrupt:
        status = 130
    finally:
        run.stop()
        if not a.keep and not remove(run.base):
            print(f"suite/run.py: {run.base} could not be removed whole: a process a test started may still hold a "
                  f"file in it", file=sys.stderr)
    for s in only:
        if s not in run.used:
            run.row(s, "ERROR", 0.0, "no test file or test of the repository matches this", None)
    wall = time.perf_counter() - t0
    budget = None if only else (a.budget if a.budget is not None else d["budget"])
    lines, verdict = report(list(run.rows.values()), run.leaks, run.n, wall, run.import_s, budget,
                            "the command line" if a.budget is not None else "suite/suite.json", a.quiet)
    if a.keep:
        lines.append(f"worker folders and logs kept in {run.base}")
    print("\n".join(lines))
    status = status or verdict
    if a.tsv:
        write_tsv(a.tsv, a.label, run.rows.values(), wall, run.n, status)
    return status


if __name__ == "__main__":
    sys.exit(main())

"""inproc.py: a hook or a command of these plugins run inside the test process, as its own process would run it.

    import inproc
    inproc.prepare(HERE)          # once, when the test module is imported: every handler module of the folder
    r = inproc.run(["sh", RUN, "stop"], input=json.dumps(payload), capture_output=True, text=True, env=env, cwd=proj)

`run` takes the arguments `subprocess.run` takes and returns what it returns, a `subprocess.CompletedProcess`. A
command line it knows runs in this process; any other goes to the real `subprocess.run` unchanged, and so does every
command when the test process starts with P4_INPROC=0. It knows:

  sh <hooks>/run-hook.sh <name>            p4-phi's runner: `${CLAUDE_PLUGIN_ROOT}/scripts/phi.py hook <name>`, exit 0
                                           whatever the script does, and nothing at all when P4_PHI=0
  sh <hooks>/recall-hook.sh <name> ...     the recall runner: `${CLAUDE_PLUGIN_ROOT}/scripts/hook.py <name> ...`, exit
                                           0, with the script's lookup-check gate, which ends a call with no python,
                                           and its rule that detaches a clean lookup-record, run here to its end with
                                           its output dropped
  sh <hooks>/run-hook.sh <part> ...        p4-temportal's runner: memory, scratchpad or lifetime, as
                                           `${CLAUDE_PLUGIN_ROOT}/hooks/<script> ...`, exit 0
  <python> [flags] <script>.py ...         a script of a prepared folder: its `if __name__ == "__main__":` block, with
                                           flags among -I, -E, -s, -S, -B, -u and -X utf8

A runner needs CLAUDE_PLUGIN_ROOT in the call's environment, and the script it reaches must be the file a prepared
module was loaded from; otherwise the call is the real process.

For one call, in this process: os.environ is the call's `env`; the working folder is its `cwd`; sys.argv is the
script's command line; sys.stdin holds its input; sys.stdout and sys.stderr are captured, encoded UTF-8 as -X utf8
encodes them; every prepared module's globals are as they were at its import, with `stand_ins` set over them;
warnings are filtered as a fresh interpreter filters them; tempfile's folder is read again from the environment; and,
with a `clock`, time.time, time.monotonic, time.sleep, time.strftime, time.localtime, time.gmtime and time.ctime read
that clock. A `SystemExit` is the exit code, and any other exception prints its traceback and exits 1. All of it is
put back after the call, the test's own values of the module globals included, as a real process leaves the test
process untouched.

Not covered, so a test of these stays a real process: the shells finding an interpreter and remembering it in
`.python`, `datetime.datetime.now` under a clock, a timeout, output a handler's child writes to an inherited handle,
and state kept in closures, class attributes or function defaults.
"""
import ast
import heapq
import io
import locale
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import warnings

REAL_RUN = subprocess.run
ENABLED = os.environ.get("P4_INPROC", "1") != "0"
PY_FLAGS = {"-I", "-E", "-s", "-S", "-B", "-u", "-3"}
TEMPORTAL_PARTS = {"memory": "p4_memory.py", "scratchpad": "scratchpad.py", "lifetime": "lifetime.py"}
KNOWN_KW = {"input", "capture_output", "text", "encoding", "errors", "universal_newlines", "env", "cwd", "timeout",
            "check", "stdin", "stdout", "stderr", "close_fds"}
STATS = {"calls": 0, "seconds": 0.0, "kinds": {}}     # read by a profiler: what ran here instead of a process

_FOLDERS = {}        # normcased folder -> folder, prepared
_NAMES = set()       # the module names the prepared folders hold, tests and this file left out
_SNAP = {}           # module name -> its module, its globals at import, and how each is put back
_MAIN = {}           # script path -> the compiled body of its `if __name__ == "__main__":` block
_RUNNERS = {}        # a runner's path -> whether it is p4-phi's run-hook.sh, whether p4-temportal's
_DEPTH = [0]
_REAL_TIME = {n: getattr(time, n) for n in ("time", "monotonic", "sleep", "strftime", "localtime", "gmtime", "ctime")}


# --- the modules a call finds as they were at import -------------------------------------------------------------

def prepare(folder):
    """Import every module of `folder` but its tests, and keep each one's globals as they are now, before any test
    runs: every call starts from them. Call it when the test module is imported. A name two folders hold, such as
    p4conf, is one module, loaded from the folder first on sys.path."""
    folder = os.path.abspath(folder)
    key = os.path.normcase(folder)
    if key in _FOLDERS:
        return
    _FOLDERS[key] = folder
    if not any(os.path.normcase(os.path.abspath(p or ".")) == key for p in sys.path):
        sys.path.append(folder)
    import importlib
    for f in sorted(os.listdir(folder)):
        name = f[:-3]
        if f.endswith(".py") and not f.startswith("test_") and name != "inproc":
            _NAMES.add(name)
            if name not in sys.modules:
                importlib.import_module(name)
    _snapshot()


def _prepared(path):
    return os.path.normcase(os.path.dirname(os.path.abspath(path))) in _FOLDERS


def _copy(v, memo):
    """A value as fresh as at import: dicts, lists, sets and the tuples that hold them copied, deep; a thread-local
    made anew; everything else, functions, modules, patterns and frozen values, the same object."""
    t = type(v)
    if t in (str, int, float, bool, bytes, type(None), frozenset):
        return v
    i = id(v)
    if i in memo:
        return memo[i]
    if isinstance(v, threading.local):
        c = t()
    elif isinstance(v, dict):
        c = dict() if t is dict else v.copy()
        if t is not dict:
            c.clear()
        memo[i] = c
        for k, x in v.items():
            c[k] = _copy(x, memo)
        return c
    elif isinstance(v, list):
        c = []
        memo[i] = c
        c.extend(_copy(x, memo) for x in v)
        return c if t is list else t(c)
    elif isinstance(v, (set, bytearray)):
        c = t(v)
    elif t is tuple:
        items = tuple(_copy(x, memo) for x in v)
        c = v if all(a is b for a, b in zip(items, v)) else items
    else:
        return v
    memo[i] = c
    return c


MUTABLE = (dict, list, set, bytearray, threading.local)


def _pure(v, seen=None):
    """True when nothing in `v`, at any depth, can change: no dict, list, set, bytearray or thread-local in it."""
    if isinstance(v, MUTABLE):
        return False
    if type(v) is tuple:
        seen = seen or set()
        if id(v) in seen:
            return True
        seen.add(id(v))
        return all(_pure(x, seen) for x in v)
    return True


def _how(v):
    """0: the value as it is; 1: a flat copy, its items being pure; 2: a deep copy."""
    if _pure(v):
        return 0
    if type(v) in (dict, list, set, bytearray) and all(_pure(x) for x in (v.values() if type(v) is dict else v)):
        return 1
    return 2


def _snapshot():
    memo = {}
    for name in sorted(_NAMES):
        mod = sys.modules.get(name)
        if name in _SNAP or mod is None:
            continue
        ns = {k: _copy(v, memo) for k, v in vars(mod).items() if not k.startswith("__")}
        how = {k: _how(v) for k, v in ns.items()}
        how[None] = len(vars(mod)) - len(ns)                       # its dunder names, which no call changes
        _SNAP[name] = (mod, ns, how)


def _fresh_modules(stand_ins):
    """Every prepared module's globals put back as at import, then the stand-ins over them. A value two modules
    share stays one value."""
    memo = {}
    for name, (mod, ns, how) in _SNAP.items():
        d = vars(mod)
        if len(d) != len(ns) + how[None]:
            for k in [k for k in d if k not in ns and not k.startswith("__")]:
                del d[k]
        for k, v in ns.items():
            h = how[k]
            if h == 0:
                d[k] = v
            elif h == 1:
                c = memo.get(id(v))
                if c is None:
                    c = memo[id(v)] = v.copy()
                d[k] = c
            else:
                d[k] = _copy(v, memo)
    for dotted, value in (stand_ins or {}).items():
        mod, _, attr = dotted.rpartition(".")
        setattr(sys.modules[mod], attr, value)


# --- what the runners do before python starts ---------------------------------------------------------------------

def _any(payload, words):
    return any(w in payload for w in words)


def _tool(*names):
    return [f'"tool_name":"{n}"'.encode() for n in names] + [f'"tool_name": "{n}"'.encode() for n in names]


EDITS = _tool("Edit", "Write", "MultiEdit", "NotebookEdit")
WEB = _tool("WebFetch", "WebSearch")
SHELLS = _tool("Bash", "PowerShell")
OTHERS = [b"mcp__ccd_session_mgmt__archive_session", b"mcp__ccd_session__start_session",
          b"mcp__ccd_session_mgmt__set_session_model", b"mcp__ccd_session_mgmt__send_message"] + _tool(
    "EnterWorktree", "SendMessage")                # a message to another session: phi.py's go-guard reads it
LONG = re.compile(rb"test_.*\.py|pytest|py\.test|unittest|npm.*test|npm.*build|cargo.*test|cargo.*build|go.*test|"
                  rb"go.*build|make.*test|make.*build", re.S)
KEEP = re.compile(rb"mcp__ccd_turn__update_plan|mcp__ccd_turn__wrap_up|temportal.*memory|PostToolUseFailure|Traceback|Error|Exception|"
                  rb"not found|not recognized|No such file|fatal:|denied|ENAMETOOLONG|unexpected EOF|cannot access|"
                  rb"unterminated", re.S)


# what may land work however git or gh is called: push, merge, or the program gh, ezexe/p4#232
LANDS = re.compile(rb"push|merge|(?:[^A-Za-z0-9_.-]|\\[ntr])gh[^A-Za-z0-9_-]")


def gate(payload, project):
    """recall-hook.sh's lookup-check gate: True when it lets python run, False when the script ends with exit 0.
    `payload` is the hook's input as bytes, `project` the folder CLAUDE_PROJECT_DIR names, '.' read from the call's
    working folder."""
    phi = os.path.join(project, ".claude", "p4", "phi")
    sub = nudge = False
    if b'"agent_id"' in payload:
        a = os.path.join(phi, ".agents")
        try:
            sub = os.path.isdir(a) and bool(os.listdir(a))
        except OSError:
            sub = False
    for folder in (".nudge", ".puppeteers"):        # a session owing a nudge, and a puppeteer
        try:
            marks = sorted(n for n in os.listdir(os.path.join(phi, folder)) if not n.startswith("."))
        except OSError:
            marks = []
        for n in marks:
            if not os.path.exists(os.path.join(phi, folder, n)):
                break
            if os.fsencode(n) in payload:
                nudge = True
                break
    if not sub:
        if _any(payload, EDITS):
            if not nudge:
                return False
        elif not _any(payload, WEB + SHELLS + OTHERS):
            return False
    if not sub and not nudge and b"git" not in payload and not LANDS.search(payload) and not LONG.search(payload) \
            and _any(payload, SHELLS):
        line = None
        for m in (("phi", "models"), ("recall", "models"), ("models",)):
            path = os.path.join(project, ".claude", "p4", *m, "lookups-model.json")
            if os.access(path, os.R_OK):
                try:
                    with open(path, "rb") as f:
                        line = f.readline()
                except OSError:
                    line = b""
                break
        if line is None or b'"shell":{"w":{}' in line:
            return False
    return True


def detaches(payload, env):
    """recall-hook.sh's rule for lookup-record: True when the python runs behind the call, its output dropped."""
    return env.get("P4_RECALL_SYNC", "0") != "1" and not KEEP.search(payload)


# --- one call ----------------------------------------------------------------------------------------------------

def _upper(env):
    return {k.upper(): v for k, v in env.items()} if os.name == "nt" else dict(env)


def _module_for(script):
    """The prepared module loaded from `script`, None when there is none."""
    script = os.path.abspath(script)
    if not _prepared(script):
        return None
    mod = sys.modules.get(os.path.splitext(os.path.basename(script))[0])
    f = getattr(mod, "__file__", None)
    if not f or os.path.normcase(os.path.abspath(f)) != os.path.normcase(script):
        return None
    return mod


def _main_code(script):
    if script not in _MAIN:
        with open(script, encoding="utf-8") as f:
            tree = ast.parse(f.read(), script)
        body = []
        for node in tree.body:
            t = getattr(node, "test", None)
            if isinstance(node, ast.If) and isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) \
                    and t.left.id == "__name__" and len(t.comparators) == 1 \
                    and getattr(t.comparators[0], "value", None) == "__main__":
                body = node.body
        _MAIN[script] = compile(ast.Module(body=body, type_ignores=[]), script, "exec")
    return _MAIN[script]


def _python(argv):
    """The script and its arguments of a python command line this harness can run, None otherwise."""
    exe = os.path.basename(argv[0].replace("\\", "/")).lower()
    exe = exe[:-4] if exe.endswith(".exe") else exe
    if not (re.fullmatch(r"python[0-9.]*w?|py", exe) or os.path.normcase(os.path.abspath(argv[0])) ==
            os.path.normcase(os.path.abspath(sys.executable))):
        return None
    i = 1
    while i < len(argv) and argv[i].startswith("-"):
        if argv[i] in PY_FLAGS:
            i += 1
        elif argv[i] == "-X" and i + 1 < len(argv) and argv[i + 1] in ("utf8", "utf8=1"):
            i += 2
        elif argv[i] in ("-Xutf8", "-Xutf8=1"):
            i += 1
        else:
            return None
    if i >= len(argv) or not argv[i].endswith(".py"):
        return None
    return argv[i], argv[i + 1:]


def plan(args, env=None, cwd=None):
    """What a command line runs here: its kind, the script and the script's arguments, or None for a real process."""
    if isinstance(args, (str, bytes)) or not args:
        return None
    argv = [os.fsdecode(a) for a in args]
    env = _upper(os.environ if env is None else env)
    here = os.path.abspath(cwd or os.getcwd())
    exe = os.path.basename(argv[0].replace("\\", "/")).lower()
    exe = exe[:-4] if exe.endswith(".exe") else exe
    if exe in ("sh", "bash"):
        if len(argv) < 2 or argv[1].startswith("-"):
            return None
        runner = os.path.join(here, argv[1])
        hooks, base, rest = os.path.dirname(runner), os.path.basename(runner), argv[2:]
        if runner not in _RUNNERS:
            _RUNNERS[runner] = (
                base == "run-hook.sh" and os.path.isfile(os.path.join(os.path.dirname(hooks), "scripts", "phi.py")),
                base == "run-hook.sh" and os.path.isfile(os.path.join(hooks, "scratchpad.py")))
        phi_runner, temportal = _RUNNERS[runner]
        if phi_runner and env.get("P4_PHI", "1") == "0":
            return "off", None, rest
        if temportal and (rest[:1] or [""])[0] not in TEMPORTAL_PARTS:
            return "unknown-part", None, rest
        root = env.get("CLAUDE_PLUGIN_ROOT")
        if not root:
            return None
        root = os.path.join(here, root)
        if phi_runner:
            kind, script, rest = "run-hook", os.path.join(root, "scripts", "phi.py"), ["hook", *rest]
        elif base == "recall-hook.sh":
            kind, script = "recall-hook", os.path.join(root, "scripts", "hook.py")
        elif temportal:
            kind, script, rest = "temportal", os.path.join(root, "hooks", TEMPORTAL_PARTS[rest[0]]), rest[1:]
        else:
            return None
        return (kind, script, rest) if _module_for(script) else None
    py = _python(argv)
    if py and _module_for(os.path.join(here, py[0])):
        return "py", os.path.abspath(os.path.join(here, py[0])), py[1]
    return None


def run(args, **kw):
    """`subprocess.run(args, **kw)`, run in this process when `plan` knows the command line. Two more keywords:
    `clock`, a Clock the call's time reads, and `stand_ins`, {"module.name": value} set over the module globals for
    the call, such as {"puppeteer.PROCESSES": lambda: []}."""
    clock, stand_ins = kw.pop("clock", None), kw.pop("stand_ins", None)
    p = None
    if ENABLED and not _DEPTH[0] and set(kw) <= KNOWN_KW and kw.get("stdin") in (None, subprocess.DEVNULL,
                                                                                    subprocess.PIPE) \
            and kw.get("stdout") in (None, subprocess.PIPE, subprocess.DEVNULL) \
            and kw.get("stderr") in (None, subprocess.PIPE, subprocess.DEVNULL, subprocess.STDOUT):
        p = plan(args, kw.get("env"), kw.get("cwd"))
    if p is None:
        return REAL_RUN(args, **kw)
    t0 = time.perf_counter()
    try:
        return _here(args, p, kw, clock, stand_ins)
    finally:
        dt = time.perf_counter() - t0
        k = "inproc:" + (p[0] if p[0] != "py" else "py:" + os.path.basename(p[1]))
        STATS["calls"] += 1
        STATS["seconds"] += dt
        c = STATS["kinds"].setdefault(k, [0, 0.0])
        c[0] += 1
        c[1] += dt


def _here(args, p, kw, clock, stand_ins):
    kind, script, rest = p
    text = bool(kw.get("text") or kw.get("universal_newlines") or kw.get("encoding") or kw.get("errors"))
    enc = kw.get("encoding") or locale.getpreferredencoding(False)
    errs = kw.get("errors") or "strict"
    data = kw.get("input")
    if data is None or kw.get("stdin") == subprocess.DEVNULL:
        data = b""
    elif isinstance(data, str):
        data = data.replace("\n", os.linesep).encode(enc, errs)     # a text pipe, as subprocess writes it
    env = kw.get("env")
    envu = _upper(os.environ if env is None else env)
    rc, out, err = 0, b"", b""
    if kind == "unknown-part":
        out = f"p4-temportal: unknown part '{(rest[:1] or [''])[0]}'; nothing was done\n".encode()
    elif kind == "recall-hook" and (rest[:1] or [""])[0] in ("lookup-check", "lookup-record"):
        payload = data.rstrip(b"\n")                                # payload=$(cat)
        project = os.path.join(os.path.abspath(kw.get("cwd") or os.getcwd()), envu.get("CLAUDE_PROJECT_DIR") or ".")
        if rest[0] == "lookup-check" and not gate(payload, project):
            pass
        elif rest[0] == "lookup-record" and detaches(payload, envu):
            _call(script, rest, payload, env, kw.get("cwd"), clock, stand_ins)
        else:
            _, out, err = _call(script, rest, payload, env, kw.get("cwd"), clock, stand_ins)
    elif kind != "off":
        rc, out, err = _call(script, rest, data, env, kw.get("cwd"), clock, stand_ins)
        if kind != "py":
            rc = 0                                                  # every runner ends with exit 0
    def give(b, where, stream):
        if kw.get("capture_output") or where == subprocess.PIPE:
            return _text(b, enc, errs) if text else b
        if where is None and b:                                     # inherited: the test process's own stream
            stream.write(_text(b, enc, "replace"))
        return None
    if kw.get("stderr") == subprocess.STDOUT:
        so, se = give(out + err, kw.get("stdout"), sys.stdout), None
    else:
        so, se = give(out, kw.get("stdout"), sys.stdout), give(err, kw.get("stderr"), sys.stderr)
    r = subprocess.CompletedProcess(args, rc, so, se)
    if kw.get("check") and rc:
        raise subprocess.CalledProcessError(rc, args, so, se)
    return r


def _text(b, enc, errs):
    return b.decode(enc, errs).replace("\r\n", "\n").replace("\r", "\n")


def _set_environ(env):
    for k in list(os.environ):
        if k not in env:
            del os.environ[k]
    for k, v in env.items():
        if os.environ.get(k) != v:
            os.environ[k] = v


def _call(script, argv, data, env, cwd, clock, stand_ins):
    """Run a prepared script's main block here: its exit code, and its stdout and stderr as bytes."""
    mod = _module_for(script)
    code = _main_code(os.path.abspath(script))
    held_env = dict(os.environ)
    held = (os.getcwd(), sys.argv, sys.stdin, sys.stdout, sys.stderr, list(sys.path), tempfile.tempdir,
            {k: getattr(time, k) for k in _REAL_TIME})
    held_mods = {name: dict(vars(m)) for name, (m, _, _) in _SNAP.items()}
    out_b, err_b = io.BytesIO(), io.BytesIO()
    nl = None if os.name == "nt" else "\n"                          # python on Windows writes \r\n to a pipe
    stdout = io.TextIOWrapper(out_b, encoding="utf-8", errors="surrogateescape", newline=nl)
    stderr = io.TextIOWrapper(err_b, encoding="utf-8", errors="backslashreplace", newline=nl, line_buffering=True)
    rc = 0
    _DEPTH[0] += 1
    try:
        if env is not None:
            _set_environ(dict(env))
        if cwd:
            os.chdir(cwd)
        sys.argv = [script, *argv]
        sys.stdin = io.TextIOWrapper(io.BytesIO(data), encoding="utf-8", errors="surrogateescape")
        sys.stdout, sys.stderr = stdout, stderr
        tempfile.tempdir = None
        _fresh_modules(stand_ins)
        if clock is not None:
            clock.install()
        with warnings.catch_warnings():
            warnings.resetwarnings()                                # a fresh interpreter's filters, in its order
            for action, cat, mod_re in (("default", DeprecationWarning, "__main__"), ("ignore", DeprecationWarning, ""),
                                        ("ignore", PendingDeprecationWarning, ""), ("ignore", ImportWarning, ""),
                                        ("ignore", ResourceWarning, "")):
                warnings.filterwarnings(action, category=cat, module=mod_re, append=True)
            try:
                exec(code, vars(mod))
            except SystemExit as e:
                rc = _exit_code(e.code)
            except KeyboardInterrupt:
                raise
            except BaseException:  # noqa: BLE001 -- the interpreter's last words, as a real process prints them
                traceback.print_exc(file=sys.stderr)
                rc = 1
        for s in (stdout, stderr):
            try:
                s.flush()
            except (OSError, ValueError):
                pass
        return rc, out_b.getvalue(), err_b.getvalue()
    finally:
        _DEPTH[0] -= 1
        cwd0, sys.argv, sys.stdin, sys.stdout, sys.stderr, path, tempfile.tempdir, funcs = held
        for k, f in funcs.items():
            setattr(time, k, f)
        sys.path[:] = path
        for name, ns in held_mods.items():
            d = vars(_SNAP[name][0])
            d.clear()
            d.update(ns)
        _set_environ(held_env)
        try:
            os.chdir(cwd0)
        except OSError:
            pass
        for s in (stdout, stderr):
            try:
                s.detach()
            except (OSError, ValueError):
                pass


def _exit_code(code):
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    print(code, file=sys.stderr)
    return 1


# --- a clock a call can run on ------------------------------------------------------------------------------------

class Clock:
    """Time for a call: time.time and time.monotonic read `now`, time.sleep moves it on at once and runs what fell
    due on the way, in the call's own thread, and strftime, localtime, gmtime and ctime with no time given read it.

        c = inproc.Clock()
        c.after(0.4, lambda: tree.record(late, TOP, "Late session"))
        tree.say(late, HANDED, clock=c, P4_PHI_WAIT="5")
    """

    def __init__(self, now=None):
        self.now = _REAL_TIME["time"]() if now is None else float(now)
        self._due, self._n = [], 0

    def after(self, seconds, fn):
        self.at(self.now + float(seconds), fn)

    def at(self, when, fn):
        heapq.heappush(self._due, (float(when), self._n, fn))
        self._n += 1

    def time(self):
        return self.now

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        end = self.now + max(0.0, float(seconds))
        while self._due and self._due[0][0] <= end:
            when, _, fn = heapq.heappop(self._due)
            self.now = max(self.now, when)
            fn()
        self.now = end

    def strftime(self, fmt, t=None):
        return _REAL_TIME["strftime"](fmt, _REAL_TIME["localtime"](self.now) if t is None else t)

    def localtime(self, secs=None):
        return _REAL_TIME["localtime"](self.now if secs is None else secs)

    def gmtime(self, secs=None):
        return _REAL_TIME["gmtime"](self.now if secs is None else secs)

    def ctime(self, secs=None):
        return _REAL_TIME["ctime"](self.now if secs is None else secs)

    def install(self):
        for k in _REAL_TIME:
            setattr(time, k, getattr(self, k))


# --- the copy in the other plugin ---------------------------------------------------------------------------------

def _same_as_sibling():
    """p4-phi/scripts/inproc.py and p4-temportal/hooks/inproc.py are one file in two places, as p4conf.py is."""
    here = os.path.dirname(os.path.abspath(__file__))
    plugins = os.path.dirname(os.path.dirname(here))
    pair = [os.path.join(plugins, "p4-phi", "scripts", "inproc.py"), os.path.join(plugins, "p4-temportal", "hooks",
                                                                                  "inproc.py")]
    if all(os.path.isfile(p) for p in pair):
        with open(pair[0], "rb") as a, open(pair[1], "rb") as b:
            if a.read() != b.read():
                raise ImportError("inproc.py differs between p4-phi/scripts and p4-temportal/hooks; copy one over the "
                                  "other")


_same_as_sibling()

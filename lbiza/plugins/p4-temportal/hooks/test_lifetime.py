#!/usr/bin/env python3
"""test_lifetime.py — p4-temportal's cookie and cache lifetimes, and the layout move run at a start.

    python -I -X utf8 lbiza/plugins/p4-temportal/hooks/test_lifetime.py
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lifetime  # noqa: E402
import p4conf  # noqa: E402

DAY = 86400

def wipe(path):
    """Remove a test's tree, a git repository's read-only objects included, which rmtree alone leaves on Windows."""
    def again(fn, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            fn(p)
        except OSError:
            pass
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=again)
    else:
        shutil.rmtree(path, onerror=again)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def put(path, text="x", age_days=0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if age_days:
        t = time.time() - age_days * DAY
        os.utime(path, (t, t))
    return path


def set_aside(path, age_days, text="x"):
    """A copy as a layout move left it `age_days` ago: the file and the folder holding it both last changed then."""
    put(path, text, age_days)
    t = time.time() - age_days * DAY
    os.utime(os.path.dirname(path), (t, t))
    return path


def inproc(module, args, stdin=b"", env=None, cwd=None):
    """A hook script's main() run in this process, the way its own process would run it: its argv, its stdin, the
    environment given in place of this one, and its cwd, with stdout and stderr captured. It saves a python start per
    call."""
    import contextlib
    import importlib
    import io
    import types
    mod = importlib.import_module(module)
    saved = (dict(os.environ), os.getcwd(), sys.argv, sys.stdin)
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="\n", write_through=True)   # a .buffer, as a process's stdout has
    err = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="\n", write_through=True)
    code = 0
    try:
        if env is not None:
            os.environ.clear()
            os.environ.update(env)
        if cwd:
            os.chdir(cwd)
        sys.argv = [module + ".py", *args]
        sys.stdin = io.TextIOWrapper(io.BytesIO(stdin if isinstance(stdin, bytes) else stdin.encode("utf-8")),
                                     encoding="utf-8")
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = mod.main() or 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    finally:
        os.environ.clear()
        os.environ.update(saved[0])
        os.chdir(saved[1])
        sys.argv, sys.stdin = saved[2], saved[3]
    text = [f.buffer.getvalue().decode("utf-8", "replace") for f in (out, err)]
    return types.SimpleNamespace(returncode=code, stdout=text[0], stderr=text[1])


def run(*args, stdin="", cwd=None, **env):
    """lifetime.py as a process, with every CLAUDE* name of this environment removed and the names given set."""
    e = {k: v for k, v in os.environ.items() if not k.upper().startswith("CLAUDE")}
    e.update(env)
    return inproc("lifetime", args, stdin, e, cwd)


class FailureNotice(unittest.TestCase):
    """A failure on SessionEnd, where plain stdout reaches nobody, is printed as a systemMessage that ezexe sees."""

    def test_a_degraded_sweep_prints_a_system_message(self):
        import contextlib
        import io
        import lifetime
        root = tempfile.mkdtemp(prefix="p4-temportal-fail-")
        old = (lifetime.sweep, sys.argv, sys.stdin)
        def broken(*a, **k):
            raise OSError("disk gone")
        try:
            lifetime.sweep = broken
            for sub, event in (("session-end", "SessionEnd"), ("sweep", "SessionStart")):
                sys.argv = ["lifetime.py", sub]
                sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps({"cwd": root, "hook_event_name": event}).encode()))
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    lifetime.main()
                msg = json.loads(out.getvalue())["systemMessage"]
                self.assertIn(f"lifetime {sub} degraded", msg)
                self.assertIn("disk gone", msg)
        finally:
            lifetime.sweep, sys.argv, sys.stdin = old
            wipe(root)


class Tick(unittest.TestCase):
    """`tick`, the retention sweep as the hooks module runs it: at a session's start, on its timer, and let go of at
    the session's end."""
    maxDiff = None

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="p4-temportal-tick-")
        self.p4 = os.path.join(self.root, ".claude", "p4")
        self.t = os.path.join(self.p4, "temportal")
        os.makedirs(self.t)

    def tearDown(self):
        wipe(self.root)

    def test_a_tick_clears_what_is_due_and_says_when_the_next_sweep_is(self):
        """One JSON line: what the sweep cleared, without the plugin's name, which the module's log line carries, and
        the seconds until the next cookie expires."""
        due = put(os.path.join(self.t, "notebook", "due.md"))
        later = put(os.path.join(self.t, "notebook", "later.md"))
        now = time.time()
        lifetime.write_expires(self.p4, {"notebook/due.md": {"expires": now - 1},
                                         "notebook/later.md": {"expires": now + 600}})
        r = run("tick", CLAUDE_PROJECT_DIR=self.root)
        answer = json.loads(r.stdout)
        self.assertEqual((r.stdout.count("\n"), answer["said"], os.path.exists(due), os.path.exists(later)),
                         (1, ["cleared expired files: 1, notebook/due.md."], False, True))
        self.assertTrue(590 < answer["wait_s"] <= 600, answer)

    def test_the_wait_is_the_next_cookie_a_minute_at_least_and_an_hour_at_most(self):
        now = 1_000_000.0
        waits = {}
        for name, entries in (("no cookie", {}), ("due in five seconds", {"a": {"expires": now + 5}}),
                              ("due in a quarter of an hour, and in two", {"a": {"expires": now + 900},
                                                                           "b": {"expires": now + 7200}}),
                              ("due tomorrow", {"a": {"expires": now + DAY}}),
                              ("past due and left", {"memory/a.md": {"expires": now - 5}}),
                              ("unreadable", {"a": {"expires": "soon"}, "b": 7, "c": {"session": "abc"}})):
            lifetime.write_expires(self.p4, entries)
            waits[name] = lifetime.next_wait(self.p4, now)
        self.assertEqual(waits, {"no cookie": 3600.0, "due in five seconds": 60.0,
                                 "due in a quarter of an hour, and in two": 900.0, "due tomorrow": 3600.0,
                                 "past due and left": 3600.0, "unreadable": 3600.0})

    def test_a_tick_makes_the_layout_move_a_start_makes(self):
        put(os.path.join(self.p4, "memory", "a.md"))
        r = run("tick", CLAUDE_PROJECT_DIR=self.root)
        self.assertEqual((json.loads(r.stdout)["said"], os.path.isfile(os.path.join(self.t, "memory", "a.md"))),
                         (["moved memory/ to temportal/memory/."], True))

    def test_a_tick_in_a_project_with_no_store_writes_nothing(self):
        bare = os.path.join(self.root, "bare")
        os.makedirs(bare)
        r = run("tick", CLAUDE_PROJECT_DIR=bare)
        self.assertEqual((json.loads(r.stdout), os.listdir(bare)), ({"said": [], "wait_s": 3600.0}, []))

    def test_a_tick_that_fails_says_so_in_its_json_line(self):
        old = lifetime.sweep
        def broken(*a, **k):
            raise OSError("disk gone")
        try:
            lifetime.sweep = broken
            answer = lifetime.tick(self.root)
        finally:
            lifetime.sweep = old
        self.assertEqual(answer, {"said": ["the retention sweep degraded: OSError: disk gone"], "wait_s": 3600.0})

    def test_a_tick_let_go_returns_at_once_and_its_sweep_runs_in_a_process_of_its_own(self):
        """`tick --let-go` answers before any file is cleared, and the process it started clears the due cookie. It
        is a real process, as the module starts it at a session's end."""
        due = put(os.path.join(self.t, "notebook", "due.md"))
        lifetime.write_expires(self.p4, {"notebook/due.md": {"expires": 1.0}})
        calls = []
        real = subprocess.Popen
        def popen(argv, **kw):
            calls.append((argv[1:4] + argv[5:], sorted(k for k, v in kw.items() if v)))
            return real(argv, **dict(kw, env=dict(os.environ, CLAUDE_PROJECT_DIR=self.root)))
        import warnings
        try:
            subprocess.Popen = popen
            with warnings.catch_warnings():     # the process is let go of while it runs, which is the point
                warnings.simplefilter("ignore", ResourceWarning)
                answer = lifetime.tick(self.root, to_let_go=True)
        finally:
            subprocess.Popen = real
        for _ in range(200):
            if not os.path.exists(due):
                break
            time.sleep(0.05)
        own = "creationflags" if os.name == "nt" else "start_new_session"
        self.assertEqual((answer, os.path.exists(due), calls),
                         ({"let_go": True}, False,
                          [(["-I", "-X", "utf8", "tick"], sorted(["close_fds", own, "stderr", "stdin", "stdout"]))]))

    def test_with_no_process_to_let_go_of_the_sweep_runs_in_the_one_that_asked(self):
        due = put(os.path.join(self.t, "notebook", "due.md"))
        lifetime.write_expires(self.p4, {"notebook/due.md": {"expires": 1.0}})
        old = lifetime.let_go
        try:
            lifetime.let_go = lambda args: False
            answer = lifetime.tick(self.root, to_let_go=True)
        finally:
            lifetime.let_go = old
        self.assertEqual((answer["said"], os.path.exists(due)), (["cleared expired files: 1, notebook/due.md."], False))


class Lifetime(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="p4-temportal-life-")
        self.p4 = os.path.join(self.root, ".claude", "p4")
        self.t = os.path.join(self.p4, "temportal")
        os.makedirs(self.t)

    def tearDown(self):
        wipe(self.root)

    def test_lifetimes_parse(self):
        now = 1_000_000.0
        self.assertEqual(lifetime.parse_lifetime("30m", now), now + 1800)
        self.assertEqual(lifetime.parse_lifetime("2w", now), now + 14 * DAY)
        self.assertGreater(lifetime.parse_lifetime("2099-01-01"), now)
        with self.assertRaises(ValueError):
            lifetime.parse_lifetime("soon")

    def test_the_cache_rule_clears_by_age_and_then_by_size(self):
        out = os.path.join(self.t, "notebook", ".out")
        put(os.path.join(out, ".gitignore"), "*\n", age_days=100)
        old = put(os.path.join(out, "old.log"), age_days=20)
        new = put(os.path.join(out, "new.log"), age_days=1)
        self.assertTrue(lifetime.sweep(self.p4).startswith("p4-temportal: cleared files past the cache rule: 1,"))
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(new))
        self.assertTrue(os.path.exists(os.path.join(out, ".gitignore")), "the seed is never cleared")
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"temportal": {"cache": {"notebook/.out": {"max_mb": 0.00001}}}}, f)
        big1 = put(os.path.join(out, "a.bin"), "a" * 100, age_days=3)
        big2 = put(os.path.join(out, "b.bin"), "b" * 100, age_days=2)
        lifetime.sweep(self.p4)
        self.assertFalse(os.path.exists(big1), "the oldest goes first")
        self.assertFalse(os.path.exists(big2))
        self.assertEqual(lifetime.sweep(self.p4), "", "a second retention sweep has nothing to clear")

    def test_a_size_cap_keeps_a_copy_the_same_start_set_aside(self):
        """A hand-set max_mb on the .layout-conflicts rule clears oldest first whatever the age, so a copy a layout
        move set aside in the same start must not be the one it clears."""
        put(os.path.join(self.p4, "recall", "store", "a.txt"), "a")
        kept = put(os.path.join(self.p4, "recall", ".layout-conflicts", "store", "kept.txt"), "k" * 100, age_days=60)
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"temportal": {"cache": {".layout-conflicts": {"max_mb": 0.00001}}}}, f)
        p4conf.migrate_layout(self.p4, commit=False)
        lifetime.sweep(self.p4)
        moved = os.path.join(self.p4, "phi", p4conf.LAYOUT_CONFLICTS, "recall", "store", "kept.txt")
        self.assertFalse(os.path.exists(kept))
        self.assertTrue(os.path.isfile(moved), "the copy set aside in this start is kept")

    def test_the_sweep_refuses_an_entry_set_would_refuse(self):
        """An expires.json entry written by hand for a path `set` refuses is left with its file, and `list` prints a
        cache rule that is not an object."""
        files = [put(os.path.join(self.t, "memory", "MEMORY.md")), put(os.path.join(self.t, "tmp", "s1", "n.md")),
                 put(os.path.join(self.p4, "phi", "store", "rules.md")), put(os.path.join(self.t, "notebook", "p.md"))]
        entries = {"memory/MEMORY.md": {"expires": 0}, "tmp/s1": {"expires": 0}, "../phi/store": {"expires": 0},
                   "notebook": {"expires": 0}}
        lifetime.write_expires(self.p4, entries)
        self.assertEqual(lifetime.sweep(self.p4), "")
        for f in files:
            self.assertTrue(os.path.isfile(f), f)
        self.assertEqual(lifetime.read_expires(self.p4), entries)
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"temportal": {"cache": {"probes": 7}}}, f)
        self.assertIn("probes", " ".join(lifetime.listing(self.p4)))

    def test_an_age_of_zero_keeps_a_copy_the_same_start_set_aside(self):
        """A hand-set max_age_days of 0 on the .layout-conflicts rule spares a copy this start's move set aside, as
        the size cap does."""
        put(os.path.join(self.p4, "recall", "store", "a.txt"), "a")
        put(os.path.join(self.p4, "recall", ".layout-conflicts", "store", "kept.txt"), "k", age_days=60)
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"temportal": {"cache": {".layout-conflicts": {"max_age_days": 0}}}}, f)
        p4conf.migrate_layout(self.p4, commit=False)
        lifetime.sweep(self.p4)
        moved = os.path.join(self.p4, "phi", p4conf.LAYOUT_CONFLICTS, "recall", "store", "kept.txt")
        self.assertTrue(os.path.isfile(moved), "the copy set aside in this start is kept")

    def test_a_cache_section_that_is_not_an_object_is_no_rules(self):
        import contextlib
        import io
        old = put(os.path.join(self.t, "notebook", ".out", "old.log"), age_days=400)
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"temportal": {"cache": 7}}, f)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(lifetime.sweep(self.p4), "")
            lines = lifetime.listing(self.p4)
        self.assertTrue(os.path.exists(old))
        self.assertIn("temportal.cache", err.getvalue())
        self.assertTrue(any("not an object" in x for x in lines), lines)

    def test_list_marks_an_entry_set_would_refuse(self):
        put(os.path.join(self.t, "memory", "MEMORY.md"))
        lifetime.write_expires(self.p4, {"memory/MEMORY.md": {"expires": 0}})
        line = [x for x in lifetime.listing(self.p4) if "memory/MEMORY.md" in x][0]
        self.assertIn("refused", line)
        self.assertNotIn("past due", line)

    def test_removing_a_link_into_the_store_keeps_the_store(self):
        """A link into the store is removed as a link, and the files it reaches stay."""
        target = os.path.join(self.t, "tmp", "sid")
        kept = put(os.path.join(target, "kept.md"))
        link = os.path.join(self.root, "scratchpad", "sid")
        os.makedirs(os.path.dirname(link))
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True, check=True)
        else:
            os.symlink(target, link, target_is_directory=True)
        self.assertEqual(lifetime.remove(link), 1)
        self.assertFalse(os.path.lexists(link))
        self.assertTrue(os.path.isfile(kept))

    def test_memory_is_never_cleared(self):
        mem = put(os.path.join(self.t, "memory", "a.md"), age_days=400)
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"temportal": {"cache": {"memory": {"max_age_days": 1}}}}, f)
        lifetime.sweep(self.p4)
        self.assertTrue(os.path.exists(mem))
        with self.assertRaises(ValueError):
            lifetime.set_cookie(self.p4, mem, "1m")

    def test_a_cache_rule_clears_only_its_own_folder_under_temportal(self):
        """A rule keyed memory/ another way, or keyed a folder outside temportal/, clears no file."""
        cleared = {}
        for key in ("Memory", "./memory", "notebook/../memory", "../phi/store"):
            mem = put(os.path.join(self.t, "memory", "a.md"), age_days=400)
            outside = put(os.path.join(self.p4, "phi", "store", "facts.md"), age_days=400)
            with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
                json.dump({"temportal": {"cache": {key: {"max_age_days": 1}}}}, f)
            line = lifetime.sweep(self.p4)
            gone = [os.path.relpath(p, self.p4).replace("\\", "/") for p in (mem, outside) if not os.path.exists(p)]
            if gone or line:
                cleared[key] = gone + [line]
        self.assertEqual(cleared, {}, "a cache rule cleared files outside its own folder under temportal/")

    def test_older_copies_a_layout_move_set_aside_in_phi_are_cleared_too(self):
        """The rule of .layout-conflicts clears phi/.layout-conflicts/ as it clears temportal/.layout-conflicts/, and
        the removal of a copy the store's git tracks is staged."""
        old_t = set_aside(os.path.join(self.t, ".layout-conflicts", "memory", "a.md"), 31)
        new_phi = put(os.path.join(self.p4, "phi", ".layout-conflicts", "store", "rules.md"), age_days=1)
        old_phi = set_aside(os.path.join(self.p4, "phi", ".layout-conflicts", "store", "facts.md"), 31)
        git = shutil.which("git")
        if git:
            g = lambda *a: subprocess.run([git, "-C", self.p4, *a], capture_output=True, text=True, check=True).stdout
            g("init", "-q")
            g("add", "-A")
            g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "store")
        line = lifetime.sweep(self.p4)
        self.assertEqual([os.path.exists(p) for p in (old_t, old_phi, new_phi)], [False, False, True], line)
        if git:
            self.assertIn("D\tphi/.layout-conflicts/store/facts.md", g("diff", "--cached", "--name-status"))

    def test_a_copy_set_aside_at_a_start_survives_the_sweep_of_that_start(self):
        """A copy last changed 40 days ago that the layout move of a start sets aside in temportal/.layout-conflicts/
        and in phi/.layout-conflicts/ is still there after the retention sweep the same hook runs next. The line of the
        move that says it was kept is all the hook prints."""
        put(os.path.join(self.t, "memory", "a.md"), "new\n")
        put(os.path.join(self.p4, "memory", "a.md"), "old\n", age_days=40)
        put(os.path.join(self.p4, "phi", "store", "facts.md"), "new\n")
        put(os.path.join(self.p4, "store", "facts.md"), "old\n", age_days=40)
        r = run("sweep", stdin="{}", CLAUDE_PROJECT_DIR=self.root)
        kept = [os.path.join(self.t, ".layout-conflicts", "memory", "a.md"),
                os.path.join(self.p4, "phi", ".layout-conflicts", "store", "facts.md")]
        self.assertEqual((r.stdout, [read(p) if os.path.exists(p) else "gone" for p in kept]),
                         ("p4-temportal: moved memory/ to temportal/memory/, differing files: 1, kept in "
                          "temportal/.layout-conflicts/; moved store/ to phi/store/, differing files: 1, kept in "
                          "phi/.layout-conflicts/.\n", ["old\n", "old\n"]))

    def test_a_copy_whose_file_and_folder_are_past_the_rule_is_cleared(self):
        """A copy in temportal/.layout-conflicts/ or phi/.layout-conflicts/ whose file and folder both last changed
        40 days ago is past the rule of 30 days, and the retention sweep clears it."""
        copies = [set_aside(os.path.join(self.t, ".layout-conflicts", "memory", "a.md"), 40),
                  set_aside(os.path.join(self.p4, "phi", ".layout-conflicts", "store", "facts.md"), 40)]
        r = run("--p4", self.p4, "now")
        self.assertEqual((r.stdout, [os.path.exists(p) for p in copies]),
                         ("p4-temportal: cleared files past the cache rule: 1, in .layout-conflicts/; files past the "
                          "cache rule: 1, in ../phi/.layout-conflicts/.\n", [False, False]))

    def test_no_layout_conflicts_folder_is_cleared_through_a_link(self):
        """A phi/ or a .layout-conflicts/ that is a link clears nothing in the folder it reaches, where a file past the
        rule of 30 days stays. The links of phi/ and phi/.layout-conflicts/ reach folders outside the store, and the
        link of temportal/.layout-conflicts/ reaches the notebook."""
        outside = os.path.join(self.root, "outside")
        cases = [("phi", os.path.join(outside, "phi"), (".layout-conflicts", "store", "facts.md")),
                 ("phi/.layout-conflicts", os.path.join(outside, "conflicts"), ("store", "facts.md")),
                 ("temportal/.layout-conflicts", os.path.join(self.t, "notebook"), ("plan.md",))]
        cleared = {}
        for place, target, inside in cases:
            reached = set_aside(os.path.join(target, *inside), 40)
            link = os.path.join(self.p4, *place.split("/"))
            os.makedirs(os.path.dirname(link), exist_ok=True)
            p4conf._make_link(link, target)
            try:
                r = run("--p4", self.p4, "now")
            finally:
                p4conf._unlink(link)
            if not os.path.exists(reached) or r.stdout != "nothing has expired\n":
                cleared[place] = r.stdout.strip()
        self.assertEqual(cleared, {}, "the rule of .layout-conflicts cleared a folder through a link")

    def test_the_sweep_stages_only_the_removals_it_made(self):
        """After a retention sweep in a store that is its own git repository, the deletion of each file it cleared is
        staged, and a pending change to a memory file or to a session scratchpad directory stays unstaged."""
        git = shutil.which("git")
        if not git:
            self.skipTest("no git")
        g = lambda *a: subprocess.run([git, "-C", self.p4, *a], capture_output=True, text=True, check=True).stdout
        mem = put(os.path.join(self.t, "memory", "a.md"), "a\n")
        pad = put(os.path.join(self.t, "tmp", "s1", "n.md"), "n\n")
        page = put(os.path.join(self.t, "notebook", "page.html"))
        probe = put(os.path.join(self.t, "notebook", "probe", "out.txt"))
        set_aside(os.path.join(self.p4, "phi", ".layout-conflicts", "store", "facts.md"), 31)
        g("init", "-q")
        g("add", "-A")
        g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "store")
        put(mem, "a\nan edit not yet committed\n")
        put(pad, "n\nanother session's line\n")
        now = time.time()
        lifetime.set_cookie(self.p4, page, "1h", now=now)
        lifetime.set_cookie(self.p4, os.path.dirname(probe), "1h", now=now)
        lifetime.sweep(self.p4, now=now + 2 * 3600)
        staged = g("diff", "--cached", "--name-status").splitlines()
        print(f"staged after the sweep: {len(staged)}, of them changes it did not make: "
              f"{sum(not s.startswith('D') for s in staged)}")
        self.assertEqual(staged, ["D\tphi/.layout-conflicts/store/facts.md", "D\ttemportal/notebook/page.html",
                                  "D\ttemportal/notebook/probe/out.txt"])
        self.assertEqual(g("diff", "--name-only").split(), ["temportal/memory/a.md", "temportal/tmp/s1/n.md"])

    def test_a_cookie_expires(self):
        page = put(os.path.join(self.t, "notebook", "page.html"))
        keep = put(os.path.join(self.t, "notebook", "keep.md"))
        probe = os.path.join(self.t, "notebook", "probe")
        put(os.path.join(probe, "out.txt"))
        now = time.time()
        lifetime.set_cookie(self.p4, page, "1h", now=now)
        lifetime.set_cookie(self.p4, "notebook/probe", "2d", now=now)
        lifetime.set_cookie(self.p4, keep, "1h", now=now)
        self.assertTrue(lifetime.clear_cookie(self.p4, keep))
        self.assertEqual(lifetime.sweep(self.p4, now=now + 60), "")
        line = lifetime.sweep(self.p4, now=now + 2 * 3600)
        self.assertIn("expired files: 1, notebook/page.html", line)
        self.assertFalse(os.path.exists(page))
        self.assertTrue(os.path.isdir(probe))
        lifetime.sweep(self.p4, now=now + 3 * DAY)
        self.assertFalse(os.path.exists(probe), "a directory cookie clears the whole directory")
        self.assertTrue(os.path.exists(keep))
        self.assertFalse(os.path.exists(os.path.join(self.t, lifetime.EXPIRES)), "an empty registry is removed")

    def test_an_unreadable_cookie_holds_back_no_other(self):
        """An entry of expires.json that cannot be read stays as it is, the retention sweep at a start still clears
        every other due cookie, and `list` prints each entry."""
        due = put(os.path.join(self.t, "notebook", "due.md"))
        put(os.path.join(self.t, lifetime.EXPIRES), json.dumps(
            {"notebook/bad.md": {"expires": "soon"}, "notebook/due.md": {"expires": 1.0}, "notebook/odd.md": 7}))
        swept = run("sweep", stdin="{}", CLAUDE_PROJECT_DIR=self.root)
        listed = run("--p4", self.p4, "list")
        self.assertEqual((swept.stdout, os.path.exists(due), listed.returncode, listed.stderr),
                         ("p4-temportal: cleared expired files: 1, notebook/due.md.\n", False, 0, ""))
        self.assertIn("cookie  notebook/bad.md  unreadable", listed.stdout)
        self.assertIn("cookie  notebook/odd.md  unreadable", listed.stdout)

    def test_no_lifetime_ends_with_a_session(self):
        """`set <path> session` is refused with a line that names the session's scratchpad directory, written as an
        older skill page gives it, with --session, and no cookie is kept."""
        f = put(os.path.join(self.t, "notebook", "state.md"))
        r = run("--p4", self.p4, "set", f, "session", "--session", "abc", CLAUDE_CODE_SESSION_ID="abc")
        self.assertEqual((r.returncode, r.stdout, lifetime.read_expires(self.p4)), (2, "", {}))
        self.assertIn("no lifetime ends with a session", r.stderr)
        self.assertIn("scratchpad directory", r.stderr)
        with self.assertRaises(ValueError):
            lifetime.parse_lifetime("Session")

    def test_a_cookie_an_earlier_version_set_for_a_session_is_never_cleared(self):
        """An entry of expires.json that an earlier version set to end with a session stays with its file through
        the sweep at that session's end, `list` says what it is, and `set` gives it a lifetime."""
        f = put(os.path.join(self.t, "notebook", "state.md"))
        lifetime.write_expires(self.p4, {"notebook/state.md": {"session": "abc12345-rest"}})
        ended = run("session-end", stdin=json.dumps({"session_id": "abc12345-rest"}), CLAUDE_PROJECT_DIR=self.root)
        swept = lifetime.sweep(self.p4, now=time.time() + 400 * DAY)
        listed = lifetime.listing(self.p4)[0]
        self.assertEqual((ended.stdout, swept, os.path.exists(f)), ("", "", True))
        self.assertEqual(listed, "cookie  notebook/state.md  set by an earlier version to end with session abc12345, "
                                 "so never cleared: set a lifetime on it or clear it")
        lifetime.set_cookie(self.p4, f, "1h")
        self.assertEqual(list(lifetime.read_expires(self.p4)["notebook/state.md"]), ["expires"])

    def test_set_reads_a_relative_path_from_the_working_folder_and_refuses_a_missing_one(self):
        """`set notes.md 7d` run inside a folder gives that folder's file a cookie, `clear` reads its path the same
        way, and a path that does not exist is refused."""
        pad = os.path.join(self.t, "notebook")
        put(os.path.join(pad, "notes.md"))
        here = run("--p4", self.p4, "set", "notes.md", "7d", cwd=pad)
        missing = run("--p4", self.p4, "set", os.path.join(pad, "gone.md"), "7d")
        kept = sorted(lifetime.read_expires(self.p4))
        cleared = run("--p4", self.p4, "clear", "notes.md", cwd=pad)
        self.assertEqual((here.returncode, missing.returncode, kept, cleared.stdout),
                         (0, 2, ["notebook/notes.md"], "cleared\n"))
        self.assertIn("does not exist", missing.stderr)

    def test_set_and_clear_take_a_cookie_as_list_prints_it(self):
        """`set notebook/notes.md 7d` run from the project's root, which holds no such path, gives the notebook's
        file a cookie, `list` prints it by those words, and `clear` takes them too, once the file is gone as well."""
        f = put(os.path.join(self.t, "notebook", "notes.md"))
        s = run("--p4", self.p4, "set", "notebook/notes.md", "7d", cwd=self.root)
        listed = run("--p4", self.p4, "list").stdout
        os.remove(f)
        first = run("--p4", self.p4, "clear", "notebook/notes.md", cwd=self.root)
        again = run("--p4", self.p4, "clear", "notebook/notes.md", cwd=self.root)
        self.assertEqual((s.returncode, s.stderr, s.stdout.startswith("notebook/notes.md: expires "),
                          "cookie  notebook/notes.md  expires" in listed, first.stdout, again.stdout),
                         (0, "", True, True, "cleared\n", "no expiry was set\n"))

    def test_a_path_the_working_folder_holds_is_read_from_it_first(self):
        """A relative path that names a file of the working folder is that file, so one outside temportal/ is refused
        though temportal/ holds a file by the same words."""
        put(os.path.join(self.t, "notebook", "notes.md"))
        put(os.path.join(self.root, "notebook", "notes.md"))
        r = run("--p4", self.p4, "set", "notebook/notes.md", "7d", cwd=self.root)
        self.assertEqual((r.returncode, lifetime.read_expires(self.p4)), (2, {}))
        self.assertIn("is not under", r.stderr)

    def test_no_cookie_on_tmp_or_on_the_folders_and_file_of_temportal_itself(self):
        """A cookie on tmp/ or anything in it, or on the notebook, src/ or expires.json themselves, is refused, since
        tmp/ holds only what an earlier version kept for each session's scratchpad and those are never cleared whole."""
        put(os.path.join(self.t, "tmp", "s1", "probe", "out.txt"))
        put(os.path.join(self.t, "src", "kept.py"))
        lifetime.set_cookie(self.p4, put(os.path.join(self.t, "notebook", "page.html")), "1d")
        accepted = []
        for rel in ("tmp", "tmp/s1", "tmp/s1/probe", "tmp/s1/probe/out.txt", "Tmp/s1", "notebook", "src",
                    lifetime.EXPIRES):
            try:
                lifetime.set_cookie(self.p4, os.path.join(self.t, *rel.split("/")), "1d")
                accepted.append(rel)
            except ValueError:
                pass
        self.assertEqual((accepted, sorted(lifetime.read_expires(self.p4))), ([], ["notebook/page.html"]))

    def test_a_path_outside_temportal_is_refused(self):
        with self.assertRaises(ValueError):
            lifetime.set_cookie(self.p4, os.path.join(self.p4, "p4.json"), "1d")

    def test_the_start_hook_prints_the_layout_move_it_made(self):
        """When the retention sweep's hook is the first at a start to take the layout lock, it prints the lines of
        the move, as the memory and scratchpad hooks print them."""
        put(os.path.join(self.p4, "memory", "a.md"))
        r = run("sweep", stdin="{}", CLAUDE_PROJECT_DIR=self.root)
        self.assertEqual((r.stdout, os.path.isfile(os.path.join(self.t, "memory", "a.md"))),
                         ("p4-temportal: moved memory/ to temportal/memory/.\n", True))

    def test_the_cli(self):
        f = put(os.path.join(self.t, "notebook", "n.md"))
        r = run("--p4", self.p4, "set", f, "3d")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("--p4", self.p4, "list")
        self.assertIn("cookie  notebook/n.md  expires", r.stdout)
        self.assertIn("cache   notebook/.out/", r.stdout)


class Layout(unittest.TestCase):
    """A store with files in an earlier place of the layout moves them into each plugin's folder, once, as one
    commit."""

    def setUp(self):
        self.p4 = tempfile.mkdtemp(prefix="p4-temportal-layout-")
        self.git = shutil.which("git")

    def tearDown(self):
        wipe(self.p4)

    def g(self, *a):
        return subprocess.run([self.git, "-C", self.p4, *a], capture_output=True, text=True, check=True).stdout

    def test_a_flat_store_moves_and_is_committed(self):
        put(os.path.join(self.p4, "memory", "MEMORY.md"), "- [a](a.md)\n")
        put(os.path.join(self.p4, "store", "facts.md"), "f\n")
        put(os.path.join(self.p4, "models", "eval.tsv"), "round\n")
        put(os.path.join(self.p4, "models", "served", "x.json"), "{}")
        put(os.path.join(self.p4, "scratchpad", "note.md"), "n\n")
        put(os.path.join(self.p4, "tmp", "sid1", "a.md"), "a\n")
        put(os.path.join(self.p4, ".gitignore"), "scratchpad/.out/\nmodels/served/\n/models/*.tmp\n__pycache__/\n")
        put(os.path.join(self.p4, ".gitattributes"), "models/*.pt filter=lfs\n")
        if self.git:
            self.g("init", "-q")
            self.g("add", "-A")
            self.g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "flat")
        lines = p4conf.migrate_layout(self.p4)
        self.assertEqual(len(lines), 4, lines)
        for k in p4conf.LAYOUT:
            if k != "src":
                self.assertFalse(os.path.exists(os.path.join(self.p4, k)), k)
        self.assertTrue(os.path.isfile(os.path.join(self.p4, "temportal", "memory", "MEMORY.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.p4, "phi", "store", "facts.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.p4, "temportal", "notebook", "note.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.p4, "tmp", "sid1", "a.md")), "an old tmp/ is left as it is")
        with open(os.path.join(self.p4, ".gitignore"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "temportal/notebook/.out/\nphi/models/served/\n/phi/models/*.tmp\n"
                                       "__pycache__/\n")
        with open(os.path.join(self.p4, ".gitattributes"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "phi/models/*.pt filter=lfs\n")
        if self.git:
            self.assertEqual(self.g("status", "--porcelain").strip(), "", "the move is committed whole")
            self.assertIn("R100\tstore/facts.md\tphi/store/facts.md",
                          self.g("show", "-M", "--name-status", "--format=", "HEAD"))
        self.assertEqual(p4conf.migrate_layout(self.p4), [], "a second start has nothing to move")

    def test_a_store_of_the_recall_plugin_moves_into_phi(self):
        put(os.path.join(self.p4, "recall", "store", "rules.md"), "r\n")
        put(os.path.join(self.p4, "recall", "models", "eval.tsv"), "round\n")
        put(os.path.join(self.p4, "phi", "sessions", "s", "session.json"), "{}")
        put(os.path.join(self.p4, "models", "late.json"), "{}")         # from a machine whose plugin is behind
        put(os.path.join(self.p4, ".gitignore"), "recall/models/served/\nmodels/view/\n")
        if self.git:
            self.g("init", "-q")
            self.g("add", "-A")
            self.g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "recall layout")
        lines = p4conf.migrate_layout(self.p4)
        self.assertIn("moved recall/store/ to phi/store/", lines)
        self.assertIn("moved recall/models/ to phi/models/", lines)
        self.assertIn("moved models/ to phi/models/", lines)
        self.assertFalse(os.path.exists(os.path.join(self.p4, "recall")), "recall/ is gone once emptied")
        for rel in (("phi", "store", "rules.md"), ("phi", "models", "eval.tsv"), ("phi", "models", "late.json"),
                    ("phi", "sessions", "s", "session.json")):
            self.assertTrue(os.path.isfile(os.path.join(self.p4, *rel)), rel)
        self.assertEqual(read(os.path.join(self.p4, ".gitignore")), "phi/models/served/\nphi/models/view/\n")
        if self.git:
            self.assertEqual(self.g("status", "--porcelain").strip(), "", "the move is committed whole")
        self.assertEqual(p4conf.migrate_layout(self.p4), [])

    def test_the_layout_commit_holds_the_move_and_nothing_else(self):
        """A pending hook edit stays pending, a seed block appended to .gitignore before the start stays an edit of
        its own rather than going into the layout commit, and its line in the earlier form is not left twice."""
        if not self.git:
            self.skipTest("no git")
        put(os.path.join(self.p4, "phi", "store", "facts.md"), "a fact\n")
        put(os.path.join(self.p4, ".gitignore"), "phi/models/index.json\n")
        self.g("init", "-q")
        self.g("add", "-A")
        self.g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "new layout")
        put(os.path.join(self.p4, "phi", "store", "facts.md"), "a fact\na second fact, not yet committed\n")
        put(os.path.join(self.p4, "store", "messages", "old.md"), "an old plugin's row\n")
        put(os.path.join(self.p4, "models", "tasks.tsv"), "id\ttext\n")
        with open(os.path.join(self.p4, ".gitignore"), "a", encoding="utf-8") as f:
            f.write("# seeded by p4-recall\nmodels/index.json\n")
        p4conf.migrate_layout(self.p4)
        committed = self.g("show", "--name-only", "--format=", "HEAD").split()
        self.assertEqual(sorted(committed), ["phi/models/tasks.tsv", "phi/store/messages/old.md"])
        status = sorted(self.g("status", "--porcelain").split())
        self.assertEqual(status, [".gitignore", "M", "M", "phi/store/facts.md"])
        self.assertEqual(read(os.path.join(self.p4, ".gitignore")).splitlines().count("phi/models/index.json"), 1)

    def test_a_flat_line_for_a_folder_that_never_existed_is_rewritten_too(self):
        """A store with no scratchpad/ at its top still has its `scratchpad/.out/` line rewritten, and so does the
        line of the notebook's place before it moved to temportal/notebook/."""
        put(os.path.join(self.p4, "store", "facts.md"), "f\n")
        put(os.path.join(self.p4, ".gitignore"), "scratchpad/.out/\nmodels/served/\ntemportal/scratchpad/.out/\n")
        p4conf.migrate_layout(self.p4, commit=False)
        self.assertEqual(read(os.path.join(self.p4, ".gitignore")),
                         "temportal/notebook/.out/\nphi/models/served/\n", "rewritten, and not left twice")

    def test_the_older_of_two_differing_ignored_caches_is_set_aside_uncommitted(self):
        """Of two differing copies of a cache the store ignores, the newer stays and the older is set aside in the
        plugin's .layout-conflicts/, as a tracked file's is, and is never committed."""
        if not self.git:
            self.skipTest("no git")
        put(os.path.join(self.p4, ".gitignore"), "recall/models/index.json\n")
        put(os.path.join(self.p4, "phi", "models", "index.json"), "new", age_days=0)
        put(os.path.join(self.p4, "recall", "models", "index.json"), "old", age_days=1)
        put(os.path.join(self.p4, "recall", "store", "facts.md"), "f\n")
        self.g("init", "-q")
        self.g("add", "-A")
        self.g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "split")
        p4conf.migrate_layout(self.p4)
        self.assertEqual(read(os.path.join(self.p4, "phi", "models", "index.json")), "new", "the newer stays")
        self.assertEqual(read(os.path.join(self.p4, "phi", ".layout-conflicts", "models", "index.json")), "old",
                         "the older is set aside, not deleted")
        self.assertNotIn(".layout-conflicts", self.g("ls-files"))

    def test_an_old_plugin_writing_after_the_move_is_merged(self):
        put(os.path.join(self.p4, "temportal", "memory", "a.md"), "new\n")
        put(os.path.join(self.p4, "temportal", "memory", "same.md"), "s\n")
        put(os.path.join(self.p4, "memory", "a.md"), "old\n", age_days=1)
        put(os.path.join(self.p4, "memory", "same.md"), "s\n")
        put(os.path.join(self.p4, "memory", "b.md"), "b\n")
        lines = p4conf.migrate_layout(self.p4, commit=False)
        self.assertIn("differing files: 1, kept in temportal/.layout-conflicts/", lines[0])
        mem = os.path.join(self.p4, "temportal", "memory")
        self.assertEqual(read(os.path.join(mem, "a.md")), "new\n", "the newer copy stays")
        self.assertTrue(os.path.isfile(os.path.join(mem, "b.md")))
        aside = os.path.join(self.p4, "temportal", ".layout-conflicts", "memory", "a.md")
        self.assertEqual(read(aside), "old\n")
        self.assertFalse(os.path.exists(os.path.join(self.p4, "memory")))

    def test_a_layout_move_leaves_a_scratchpad_link_as_it_is(self):
        """ezexe/p4#131 row B6: each session's scratchpad is the app's, so a layout move relinks none, and a link an
        earlier version made into the store's older tmp/ still reaches the folder it reached."""
        temp = tempfile.mkdtemp(prefix="p4-temportal-harness-")
        sid = "c0ffee00-0000-4000-8000-000000000001"
        old = os.path.join(self.p4, "tmp", sid)
        put(os.path.join(old, "n.md"), "n\n")
        put(os.path.join(self.p4, "store", "facts.md"), "f\n")
        harness = os.path.join(temp, "claude", "proj", sid, "scratchpad")
        os.makedirs(os.path.dirname(harness))
        p4conf._make_link(harness, old)
        try:
            p4conf.migrate_layout(self.p4, commit=False)
            self.assertTrue(p4conf.is_link(harness))
            self.assertTrue(os.path.samefile(harness, old), "the scratchpad link was moved")
            self.assertTrue(os.path.isfile(os.path.join(harness, "n.md")))
            self.assertFalse(os.path.exists(os.path.join(self.p4, "temportal", "tmp")), "a tmp/ was moved")
        finally:
            p4conf._unlink(harness)
            wipe(temp)


if __name__ == "__main__":
    unittest.main(verbosity=1)

#!/usr/bin/env python3
"""Tests for teacher.py, the paid batches of build step 9 (fresh-marketplace.md 1a, 5.2, 5.3, 5.6, 5.7; 8.1's
`teacher --fake` bullet), and for `eval`'s raw-against-edited comparison. Every test runs offline on the fake
client: no API call, nothing spent.

Run: python3 test_teacher.py   (stdlib unittest, offline, seconds)
"""

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import p4conf  # noqa: E402
import labels as lb  # noqa: E402
import store as st  # noqa: E402
import teacher as te  # noqa: E402
import train  # noqa: E402
from test_store import write  # noqa: E402
from test_train import synthetic  # noqa: E402

NOW = "2026-11-01 18:00"


def args(*a):
    return te.parser().parse_args(["edit-labels", "--fake", "--now", NOW, "--max-usd", "100"] + list(a))


def dargs(*a):
    return te.parser().parse_args(["dictionary", "--fake", "--now", NOW, "--max-usd", "100"] + list(a))


def fargs(*a):
    return te.parser().parse_args(["facts", "--fake", "--now", NOW, "--max-usd", "100"] + list(a))


def quiet(*_a, **_k):
    pass


def facts(p4, entries):
    write(p4conf.sub(p4, "store", "facts.md"), st.render("facts.md", entries))
    st.build_index(p4)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p4 = synthetic(self.tmp.name, n_tasks=8)

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self):
        return [r for r in lb.read_tsv(lb.mpath(self.p4, lb.TRAIN)) if r.get("source") == "store+edited"]

    def edits_md(self):
        p = lb.mpath(self.p4, te.EDITS_MD)
        if not os.path.exists(p):
            return ""
        with open(p, encoding="utf-8") as f:
            return f.read()


class Prompt(Base):
    def test_prompt_built_and_parsed_back(self):
        ctx = te.Context(self.p4)
        tid = sorted(ctx.tasks)[0]
        item = te.build_item(ctx, tid, "2026-06")
        self.assertTrue(item["picks"], "the store's picks are sent")
        self.assertIn(f"Task date: {ctx.tasks[tid]['time']}", item["user"])
        self.assertIn(f"Task: {ctx.tasks[tid]['text']}", item["user"])
        for h in item["picks"]:
            self.assertIn(f"\n[{h}] ", item["user"])
        cands = [h for h in item["handles"] if h.startswith("c")]
        self.assertTrue(cands, "candidates are sent")
        self.assertLessEqual(len(cands), 2 * te.CAND_K)
        for line in item["user"].splitlines():
            if line.startswith("[c"):
                self.assertLessEqual(len(line.split("] ", 1)[1].split(" {")[0].replace(" [newer than your training]",
                                                                                         "")), te.CAND_CHARS)
        kw = te.request("claude-fable-5-1", te.edit_system("2026-06"), item["user"], te.EDIT_SCHEMA)
        self.assertEqual(kw["thinking"], {"type": "adaptive"})
        self.assertEqual(kw["output_config"]["format"]["type"], "json_schema")
        self.assertIn("wins over your own prior", kw["system"])
        self.assertIn("the newer verified one is the positive", kw["system"])
        status, data, r = te.call(te.FakeClient(), kw)
        self.assertEqual(status, "ok")
        decisions, bad = te.parse_edit(item, data)
        self.assertEqual(bad, 0)
        self.assertEqual({h for d, h, _, _ in decisions if d in ("keep", "drop")}, set(item["picks"]),
                         "every stored pick is decided")
        for d, h, eid, why in decisions:
            self.assertEqual(item["handles"][h], eid)
            self.assertTrue(why)
        # a pick the answer leaves out is kept and said so; an unknown id is ignored and counted
        decisions, bad = te.parse_edit(item, {"picks": [], "adds": [{"id": "c999", "reason": "x"}]})
        self.assertEqual(bad, 1)
        self.assertTrue(all(d == "keep" and "no decision" in why for d, _, _, why in decisions))

    def test_batch_writes_edits_and_labels_with_the_answering_model(self):
        client = te.FakeClient(answer_as="claude-fable-5-1-20261101")
        s = te.edit_labels(self.p4, args("--limit", "3"), client=client, out=quiet)
        self.assertEqual(s["edited"], 3)
        rows = self.rows()
        self.assertEqual(len({r["task"] for r in rows}), 3)
        self.assertTrue(all(r["teacher"] == "claude-fable-5-1-20261101" for r in rows), "response.model is recorded")
        self.assertTrue(all(r["edited"] == NOW and "batch:" in r["note"] and "from:pool" in r["note"] for r in rows))
        md = self.edits_md()
        self.assertEqual(md.count("\n## "), 3)
        self.assertIn("teacher: claude-fable-5-1-20261101; edited: 2026-11-01 18:00", md)
        self.assertRegex(md, r"\n- (keep|drop|add) \S+.*: shares \d+ words")
        # the newest tasks first, and an edited task is not sent again
        tasks = lb.read_tasks(self.p4)
        newest = sorted(tasks, key=lambda t: (tasks[t]["time"], t), reverse=True)[:3]
        self.assertEqual({r["task"] for r in rows}, set(newest))
        s = te.edit_labels(self.p4, args("--limit", "3"), client=te.FakeClient(), out=quiet)
        self.assertEqual(len({r["task"] for r in self.rows()}), 6)
        # training reads the edited rows in place of the raw ones of their tasks
        tl = lb.training_labels(self.p4)
        edited = {r["task"] for r in self.rows()}
        self.assertTrue(all(r["source"] == "store+edited" for r in tl if r["task"] in edited))
        sets = {x["task"]: x for x in train.build_sets(self.p4)}
        self.assertTrue(all(sets[t]["pool_like"] for t in edited if t in sets), "an edited pool task keeps the "
                                                                                 "pool's candidates")


class Newer(Base):
    def test_newer_than_cutoff_entries_included(self):
        facts(self.p4, [
            [("claim", "the axolotl relay firmware is 4.2"), ("source", "release notes"), ("verified", "yes"),
             ("since", "2026-09-01"), ("checked", "2026-10-20"), ("prior", "version"), ("time", "2026-10-20 09:00")],
            [("claim", "the axolotl relay firmware is 3.9"), ("source", "release notes"), ("verified", "yes"),
             ("time", "2025-03-01 09:00")],
            [("claim", "the axolotl relay firmware is 5.0"), ("source", "release notes"), ("verified", "yes"),
             ("time", "2026-12-01 09:00")],
        ])
        ctx = te.Context(self.p4)
        tid = next(t for t, r in ctx.tasks.items() if "axolotl" in r["text"])
        item = te.build_item(ctx, tid, "2026-06")
        sec = item["user"].split("Entries newer than your training cutoff (2026-06)")[1].split("Candidates")[0]
        self.assertIn("firmware is 4.2", sec)
        self.assertIn("[newer than your training]", sec)
        self.assertIn("checked: 2026-10-20", sec)
        self.assertIn("prior: version", sec)
        self.assertNotIn("firmware is 3.9", sec, "an entry older than the cutoff is not in the newer section")
        self.assertNotIn("firmware is 5.0", item["user"], "an entry dated after the task is not sent")
        self.assertTrue(any(h.startswith("n") for h in item["handles"]))
        # a later cutoff leaves it out; the cutoff comes from the table, config.json or --cutoff
        item2 = te.build_item(ctx, tid, "2026-10")
        sec2 = item2["user"].split("Entries newer than your training cutoff")[1].split("Candidates")[0]
        self.assertNotIn("firmware is 4.2", sec2)
        self.assertEqual(te.cutoff_of("claude-opus-5-5"), "2026-06")
        self.assertEqual(te.cutoff_of("claude-fable-5-1"), "2026-06", "an unknown cutoff is the oldest known one")
        write(lb.mpath(self.p4, "config.json"), json.dumps({"teacher-model": "claude-fable-5-1",
                                                            "teacher-cutoff": "2026-08"}))
        self.assertEqual(te.cutoff_of("claude-fable-5-1", self.p4), "2026-08")
        self.assertEqual(te.cutoff_of("claude-fable-5-1", self.p4, "2026-03"), "2026-03")
        self.assertIn("around 2026-08", te.edit_system(te.cutoff_of(te.teacher_of(self.p4), self.p4)))


class Refusal(Base):
    def test_refusal_recorded_and_skipped(self):
        tasks = lb.read_tsv(lb.mpath(self.p4, lb.TASKS))
        newest = max(tasks, key=lambda r: (r["time"], r["id"]))
        newest["text"] += " FAKE-REFUSE"
        lb.write_tsv(lb.mpath(self.p4, lb.TASKS), lb.TASK_HEAD, tasks)
        s = te.edit_labels(self.p4, args("--limit", "3"), client=te.FakeClient(), out=quiet)
        self.assertEqual((s["refused"], s["edited"]), (1, 2))
        self.assertNotIn(newest["id"], {r["task"] for r in self.rows()}, "a refused task gets no edited rows")
        md = self.edits_md()
        self.assertIn(f"## {newest['id']}", md)
        self.assertIn("- refusal: category fake", md)
        self.assertIn("(task skipped)", md)
        # still unedited, so the next run sends it again
        ctx = te.Context(self.p4)
        self.assertIn(newest["id"], te.pick_tasks(self.p4, ctx, "claude-fable-5-1", False, None))


class Cost(Base):
    def test_max_usd_refuses_before_spending(self):
        client = te.FakeClient()
        a = args("--limit", "5")
        a.max_usd = 0.01
        s = te.edit_labels(self.p4, a, client=client, out=quiet)
        self.assertEqual(s["status"], "refused")
        self.assertGreater(client.counted, 0, "the input was counted")
        self.assertEqual(client.created, [], "nothing was sent")
        self.assertFalse(os.path.exists(lb.mpath(self.p4, te.SPEND)))
        self.assertEqual(self.rows(), [])
        self.assertGreater(s["estimate"], 0.01)
        # --estimate counts and sends nothing either
        client = te.FakeClient()
        s = te.edit_labels(self.p4, args("--limit", "5", "--estimate"), client=client, out=quiet)
        self.assertEqual((s["status"], client.created), ("estimate", []))
        # the dictionary batch refuses the same way
        write(p4conf.sub(self.p4, "store", st.VOCABULARY), st.render(st.VOCABULARY, [
            st.vocab_entry_pairs("gizmo", "(pending)", '2026-10-01 — you wrote "fix the gizmo"', "correction", [],
                                 "2026-11-01 10:00")]))
        d = dargs()
        d.max_usd = 0.0001
        client = te.FakeClient()
        self.assertEqual(te.dictionary(self.p4, d, client=client, out=quiet)["status"], "refused")
        self.assertEqual(client.created, [])

    def test_spend_recorded(self):
        s = te.edit_labels(self.p4, args("--limit", "4"), client=te.FakeClient(), out=quiet)
        with open(lb.mpath(self.p4, te.SPEND), encoding="utf-8") as f:
            sp = json.load(f)
        self.assertEqual(len(sp["calls"]), 4)
        self.assertAlmostEqual(sum(c["usd"] for c in sp["calls"]), s["spent"], places=5)
        self.assertAlmostEqual(sp["total"], s["spent"], places=5)
        c = sp["calls"][0]
        self.assertAlmostEqual(c["usd"], (c["input"] * 10.0 + c["output"] * 50.0) / 1e6, places=6,
                               msg="Fable 5.1 at $10 / $50 per million")
        # appended, never replaced
        te.edit_labels(self.p4, args("--limit", "1"), client=te.FakeClient(), out=quiet)
        with open(lb.mpath(self.p4, te.SPEND), encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)["calls"]), 5)

    def test_running_spend_stops_at_the_cap(self):
        budget = te.Budget(0.0)
        plan = [("t", te.request("claude-fable-5-1", "s", "u", te.EDIT_SCHEMA), 0.01)]
        got = list(te.run_calls(self.p4, te.FakeClient(), plan, budget, "x", out=quiet))
        self.assertEqual(got, [])


class ReEdit(Base):
    def test_re_edit_picks_only_other_teacher_tasks(self):
        te.edit_labels(self.p4, args("--limit", "2", "--teacher", "claude-sonnet-5-5"), client=te.FakeClient(),
                       out=quiet)
        te.edit_labels(self.p4, args("--limit", "2"), client=te.FakeClient(), out=quiet)   # fable, the next 2
        by = te.edited_by(self.p4)
        sonnet = {t for t, m in by.items() if m == "claude-sonnet-5-5"}
        fable = {t for t, m in by.items() if m == "claude-fable-5-1"}
        self.assertEqual((len(sonnet), len(fable)), (2, 2))
        ctx = te.Context(self.p4)
        self.assertEqual(set(te.pick_tasks(self.p4, ctx, "claude-fable-5-1", True, None)), sonnet)
        self.assertEqual(set(te.pick_tasks(self.p4, ctx, "claude-sonnet-5-5", True, None)), fable)
        unedited = set(te.pick_tasks(self.p4, ctx, "claude-fable-5-1", False, None))
        self.assertFalse(unedited & (sonnet | fable))
        before = {(r["task"], r["entry"], r["teacher"]) for r in self.rows() if r["task"] in fable}
        s = te.edit_labels(self.p4, args("--re-edit"), client=te.FakeClient(), out=quiet)
        self.assertEqual(s["tasks"], 2)
        by = te.edited_by(self.p4)
        self.assertTrue(all(by[t] == "claude-fable-5-1" for t in sonnet | fable))
        self.assertEqual({(r["task"], r["entry"], r["teacher"]) for r in self.rows() if r["task"] in fable}, before,
                         "the current teacher's edits are left alone")
        self.assertEqual(len(set(te.edited_by(self.p4))), 4, "no task gained or lost its edit")

    def test_re_edit_within_budget_takes_the_newest(self):
        te.edit_labels(self.p4, args("--teacher", "claude-sonnet-5-5"), client=te.FakeClient(), out=quiet)
        a = args("--re-edit", "--estimate")
        one = te.edit_labels(self.p4, a, client=te.FakeClient(), out=quiet)["estimate"] / 8
        a = args("--re-edit")
        a.max_usd = one * 2.5
        te.edit_labels(self.p4, a, client=te.FakeClient(), out=quiet)
        by = te.edited_by(self.p4)
        tasks = lb.read_tasks(self.p4)
        redone = {t for t, m in by.items() if m == "claude-fable-5-1"}
        self.assertEqual(len(redone), 2)
        newest = sorted(tasks, key=lambda t: (tasks[t]["time"], t), reverse=True)[:2]
        self.assertEqual(redone, set(newest))


class SecondOpinion(Base):
    def test_f1(self):
        self.assertEqual(te.f1_agreement({"a": {1, 2}}, {"a": {1, 2}}), 1.0)
        self.assertAlmostEqual(te.f1_agreement({"a": {1, 2}, "b": {3}}, {"a": {1}, "b": {3, 4}}), 2 / 3)
        self.assertEqual(te.f1_agreement({"a": {1}}, {"a": {2}}), 0.0)
        self.assertAlmostEqual(te.f1_agreement({"a": {1, 2}, "x": {9}}, {"a": {1}}), 2 / 3, msg="common tasks only")

    def test_second_opinion_reported_and_held_below_the_bar(self):
        s = te.edit_labels(self.p4, args("--limit", "4", "--second-opinion", "3"), client=te.FakeClient(), out=quiet)
        self.assertEqual(s["so_tasks"], 3)
        self.assertIsNotNone(s["f1"])
        b = lb.read_batches(self.p4)[s["batch"]]
        self.assertEqual(b["second_opinion"]["model"], "claude-opus-5-5")
        self.assertEqual(len(b["second_opinion"]["tasks"]), 3)
        self.assertIn(f"agreement F1 {s['f1']:.3f}", self.edits_md())
        with open(lb.mpath(self.p4, te.SPEND), encoding="utf-8") as f:
            sp = json.load(f)
        self.assertEqual(sum(1 for c in sp["calls"] if c["model"] == "claude-opus-5-5"), 3)
        self.assertEqual(b["status"] == "held", s["f1"] < te.AGREE_MIN)
        # forced below the bar: the batch is held and its rows are not trained on
        saved = te.AGREE_MIN
        te.AGREE_MIN = 1.01
        try:
            s2 = te.edit_labels(self.p4, args("--limit", "0", "--second-opinion", "2"), client=te.FakeClient(),
                                out=quiet)
        finally:
            te.AGREE_MIN = saved
        self.assertEqual(s2["tasks"], 0, "nothing new to edit: the opinion runs on the last batch")
        self.assertTrue(s2["held"])
        self.assertIn(s["batch"], lb.held_batches(self.p4))
        tl = lb.training_labels(self.p4)
        self.assertFalse(any(r["source"] == "store+edited" for r in tl), "a held batch is not trained on")
        self.assertTrue(any(r["source"] == "pool" for r in tl if r["task"] in b["tasks"]), "its raw labels stand in")


class Dictionary(Base):
    def vocab(self, entries):
        write(p4conf.sub(self.p4, "store", st.VOCABULARY), st.render(st.VOCABULARY, entries))

    def text(self):
        with open(p4conf.sub(self.p4, "store", st.VOCABULARY), encoding="utf-8") as f:
            return f.read()

    def block(self, term):
        t = self.text()
        i = t.index(f"- term: {term}\n")
        j = t.find("\n- term:", i + 1)
        return t[i:j if j > 0 else len(t)]

    def test_never_overwrites_owner_edits(self):
        self.vocab([
            st.vocab_entry_pairs("gizmo", "(pending)", '2026-10-01 — you wrote "fix the gizmo board" and it was read '
                                 'as the gauge; you then wrote "no the gizmo board"', "correction", [], "2026-11-01"),
            st.vocab_entry_pairs("widget", "ezexe's own meaning", '2026-10-02 — you wrote "the widget"',
                                 "correction", [], "2026-11-02"),
            st.vocab_entry_pairs("doohickey", "(pending)", '2026-10-03 — you wrote "the doohickey"',
                                 "owner", [], "2026-11-03"),
        ])
        widget, owner = self.block("widget"), self.block("doohickey")
        s = te.dictionary(self.p4, dargs(), client=te.FakeClient(), out=quiet)
        self.assertEqual((s["entries"], s["written"]), (1, 1))
        g = self.block("gizmo")
        self.assertIn("  means: (fake) gizmo as in: fix the gizmo board", g)
        self.assertRegex(g, r"  means-by: claude-fable-5-1 2026-11-01 18:00 [0-9a-f]{8}")
        self.assertEqual(self.block("widget"), widget, "a meaning ezexe wrote is untouched")
        self.assertEqual(self.block("doohickey"), owner, "ezexe's entry is untouched")
        v = {x["term"]: x for x in st.read_vocabulary(self.p4)}
        self.assertFalse(v["gizmo"]["pending"])
        # a second run has nothing pending
        self.assertEqual(te.dictionary(self.p4, dargs(), client=te.FakeClient(), out=quiet)["entries"], 0)
        # ezexe edits the teacher's meaning: a re-edit by another teacher leaves it alone
        t = self.text().replace("  means: (fake) gizmo as in: fix the gizmo board", "  means: the gizmo board, mine")
        write(p4conf.sub(self.p4, "store", st.VOCABULARY), t)
        s = te.dictionary(self.p4, dargs("--re-edit", "--teacher", "claude-opus-5-5"), client=te.FakeClient(),
                          out=quiet)
        self.assertEqual(s["entries"], 0)
        self.assertIn("  means: the gizmo board, mine", self.block("gizmo"))

    def test_re_edit_rewrites_only_an_unedited_other_teacher_meaning(self):
        self.vocab([st.vocab_entry_pairs("gizmo", "(pending)", '2026-10-01 — you wrote "fix the gizmo board"',
                                         "correction", [], "2026-11-01")])
        te.dictionary(self.p4, dargs("--teacher", "claude-sonnet-5-5"), client=te.FakeClient(), out=quiet)
        self.assertIn("means-by: claude-sonnet-5-5", self.block("gizmo"))
        self.assertEqual(te.dictionary(self.p4, dargs("--re-edit", "--teacher", "claude-sonnet-5-5"),
                                       client=te.FakeClient(), out=quiet)["entries"], 0, "same teacher: nothing")
        s = te.dictionary(self.p4, dargs("--re-edit"), client=te.FakeClient(), out=quiet)
        self.assertEqual(s["written"], 1)
        self.assertIn("means-by: claude-fable-5-1", self.block("gizmo"))
        self.assertEqual(self.block("gizmo").count("  means:"), 1)

    def test_an_edit_made_during_the_batch_wins(self):
        self.vocab([st.vocab_entry_pairs("gizmo", "(pending)", '2026-10-01 — you wrote "fix the gizmo board"',
                                         "correction", [], "2026-11-01")])
        e = next(x for x in st.load_file(self.p4, st.VOCABULARY) if x.value == "gizmo")
        t = self.text().replace("  means: (pending)", "  means: what ezexe typed meanwhile")
        write(p4conf.sub(self.p4, "store", st.VOCABULARY), t)
        n = te.write_meanings(self.p4, {(e.line, "gizmo", "(pending)"): "the teacher's"}, "claude-fable-5-1", NOW)
        self.assertEqual(n, 0)
        self.assertEqual(self.text(), t)

    def test_batches_of_twenty(self):
        self.vocab([st.vocab_entry_pairs(f"term{k}", "(pending)", f'2026-10-01 — you wrote "about term{k} here"',
                                         "correction", [], "2026-11-01") for k in range(45)])
        client = te.FakeClient()
        s = te.dictionary(self.p4, dargs(), client=client, out=quiet)
        self.assertEqual((s["calls"], s["written"], len(client.created)), (3, 45, 3))
        self.assertTrue(all(not v["pending"] for v in st.read_vocabulary(self.p4)))


class Eval(Base):
    def test_raw_against_edited(self):
        self.assertIsNone(train.run_round(self.p4, write=False, now=NOW, dictionary=False)["compare"])
        te.edit_labels(self.p4, args(), client=te.FakeClient(), out=quiet)
        c = train.raw_vs_edited(self.p4)
        self.assertEqual(c["edited_tasks"], 8)
        self.assertGreaterEqual(c["n"], 3)
        self.assertIsNotNone(c["raw"])
        self.assertIsNotNone(c["edited"])
        self.assertEqual(c["ok"], c["edited"] + 1e-9 >= c["raw"])
        row = train.run_round(self.p4, write=False, now=NOW, dictionary=False)
        self.assertIn("raw against edited on held-out raw labels", row["why"])
        self.assertFalse(os.path.exists(lb.mpath(self.p4, "eval.tsv")), "eval writes nothing")
        self.assertEqual(lb.held_batches(self.p4), set(), "eval holds nothing")

    def test_train_holds_edits_below_raw(self):
        te.edit_labels(self.p4, args(), client=te.FakeClient(), out=quiet)
        # spoil the edits: the batch's rows become the noisy store's labels (the rules naming neither topic)
        bid = next(iter(lb.read_batches(self.p4)))
        noisy = synthetic(os.path.join(self.tmp.name, "n"), n_tasks=8, noisy=True)
        rows = [{**r, "source": "store+edited", "weight": "1.0", "teacher": "claude-fable-5-1", "edited": NOW,
                 "note": f"batch:{bid}; from:pool; add"} for r in lb.read_tsv(lb.mpath(noisy, lb.RAW))]
        lb.write_tsv(lb.mpath(self.p4, lb.TRAIN), lb.TRAIN_HEAD, rows)
        c = train.raw_vs_edited(self.p4)
        self.assertFalse(c["ok"], c)
        row = train.run_round(self.p4, write=True, now=NOW, dictionary=False)
        self.assertIn("edited BELOW raw", row["why"])
        self.assertEqual(lb.held_batches(self.p4), set(c["batches"]))
        self.assertFalse(any(r["source"] == "store+edited" for r in lb.training_labels(self.p4)))


class Facts(Base):
    ROWS = [
        [("fingerprint", '"should we pin cmake 4.4 everywhere or keep 3.x working?"'), ("time", "2026-10-29 11:00"),
         ("arrival", "turn"), ("state", "FRESH"), ("addressed", "Pinned 4.4 everywhere."),
         ("recommended", "You should pin 4.4 rather than keep 3.x working.")],
        [("fingerprint", '"which way is best for the mac branch name, _mac or mac?"'), ("time", "2026-11-01 11:00"),
         ("arrival", "turn"), ("state", "FRESH"), ("addressed", "Renamed it.")],
        [("fingerprint", '"fix the build"'), ("time", "2026-11-01 12:00"), ("arrival", "turn"), ("state", "FRESH"),
         ("addressed", "Fixed.")],
        [("fingerprint", '"should the worktree be deleted after the merge?"'), ("time", "2026-11-01 13:00"),
         ("arrival", "turn")],
        [("fingerprint", '"<task-notification>should it?</task-notification>"'), ("time", "2026-11-01 14:00"),
         ("arrival", "notification"), ("state", "FRESH"), ("addressed", "(a notification; complete on arrival)")],
    ]

    def setUp(self):
        super().setUp()
        self.messages(self.ROWS)

    def messages(self, rows, s8="eeee5555"):
        write(p4conf.sub(self.p4, "store", "messages", f"{s8}.md"), st.render(f"messages/{s8}.md", rows))

    def facts_entries(self):
        return st.load_file(self.p4, "facts.md")

    def test_targets_are_completed_owner_questions_newest_first(self):
        got = te.fact_targets(self.p4)
        self.assertEqual([e.time for e in got], ["2026-11-01 11:00", "2026-10-29 11:00"],
                         "a plain request, an open row and a notification are not targets")
        self.assertEqual(len(te.fact_targets(self.p4, limit=1)), 1)
        self.assertTrue(te.asks_recommendation("which approach should we take?"))
        self.assertFalse(te.asks_recommendation("we should pin it"), "a statement is not a question")
        self.assertFalse(te.asks_recommendation("what time is it?"))

    def test_writes_sourced_facts_and_never_twice(self):
        client = te.FakeClient()
        s = te.facts(self.p4, fargs(), client=client, out=quiet)
        self.assertEqual((s["tasks"], s["written"], s["status"]), (2, 2, "done"), s)
        self.assertEqual(s["searches"], 2)
        self.assertGreater(s["spent"], 2 * te.SEARCH_USD, "a search costs on top of the tokens")
        ents = self.facts_entries()
        self.assertEqual(len(ents), 2)
        rows = {e.id: e for e in st.load_file(self.p4, "messages/eeee5555.md")}
        by_from = {e.fields["from"]: e for e in ents}
        cmake = next(e for f, e in by_from.items() if rows[f].time == "2026-10-29 11:00")
        self.assertTrue(cmake.value.startswith("use the"), cmake.value)
        self.assertTrue(cmake.fields["source"].startswith("https://docs.example.org/"), cmake.fields)
        self.assertEqual(cmake.fields["verified"], NOW)
        self.assertEqual(cmake.fields["time"], "2026-10-29 11:00", "the fact is timed by ezexe's question")
        self.assertEqual(cmake.fields["by"], "claude-fable-5-1")
        self.assertEqual(st.feature_kind("facts.md", cmake), "fact sourced")
        with open(lb.mpath(self.p4, te.SPEND), encoding="utf-8") as f:
            spend = json.load(f)
        self.assertTrue(any(k.startswith("facts ") for k in spend["steps"]))
        self.assertEqual(len([c for c in spend["calls"] if "searches" in c["note"]]), 2)
        again = te.facts(self.p4, fargs(), client=client, out=quiet)
        self.assertEqual((again["tasks"], again["written"]), (0, 0), "a question answered is not asked again")
        self.assertEqual(len(self.facts_entries()), 2)
        idx = st.build_index(self.p4)
        self.assertTrue(any(d["file"] == "facts.md" and d.get("fkind") == "fact sourced" for d in idx["docs"]),
                        "recall indexes the new facts")

    def test_unsettled_and_unsourced_write_nothing(self):
        self.messages(self.ROWS[:1] + [
            [("fingerprint", '"FAKE-UNSETTLED which linker should the mac build use?"'), ("time", "2026-11-02 09:00"),
             ("arrival", "turn"), ("state", "FRESH"), ("addressed", "lld.")]])
        s = te.facts(self.p4, fargs(), client=te.FakeClient(), out=quiet)
        self.assertEqual((s["tasks"], s["written"], s["unsettled"]), (2, 1, 1), s)
        self.assertEqual(len(self.facts_entries()), 1)
        self.assertNotIn("linker", open(p4conf.sub(self.p4, "store", "facts.md"), encoding="utf-8").read())

    def test_estimate_and_budget(self):
        s = te.facts(self.p4, fargs("--estimate"), client=te.FakeClient(), out=quiet)
        self.assertEqual(s["status"], "estimate")
        self.assertGreater(s["estimate"], 2 * te.SEARCH_MAX_USES * te.SEARCH_USD, "every allowed search is assumed")
        self.assertEqual(self.facts_entries(), [])
        s = te.facts(self.p4, fargs("--max-usd", "0.001"), client=te.FakeClient(), out=quiet)
        self.assertEqual(s["status"], "refused")
        self.assertEqual(self.facts_entries(), [])
        s = te.facts(self.p4, fargs("--limit", "1"), client=te.FakeClient(), out=quiet)
        self.assertEqual((s["tasks"], s["written"]), (1, 1))

    def test_refusal_is_counted(self):
        self.messages([[("fingerprint", '"FAKE-REFUSE should we?"'), ("time", "2026-11-02 09:00"),
                        ("arrival", "turn"), ("state", "FRESH"), ("addressed", "no")]])
        s = te.facts(self.p4, fargs(), client=te.FakeClient(), out=quiet)
        self.assertEqual((s["refused"], s["written"]), (1, 0))

    def test_cli(self):
        import subprocess
        r = subprocess.run([sys.executable, os.path.join(HERE, "p4.py"), "teacher", "facts", "--p4", self.p4,
                            "--fake", "--max-usd", "5"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("2 facts written", r.stdout)


class Cli(Base):
    def test_p4_teacher_fake(self):
        import subprocess
        r = subprocess.run([sys.executable, os.path.join(HERE, "p4.py"), "teacher", "edit-labels", "--p4", self.p4,
                            "--fake", "--limit", "2", "--max-usd", "5"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("2 edited", r.stdout)
        r = subprocess.run([sys.executable, os.path.join(HERE, "p4.py"), "teacher", "edit-labels", "--p4", self.p4,
                            "--fake", "--max-usd", "0.001"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 3)
        self.assertIn("nothing was sent", r.stdout)


if __name__ == "__main__":
    unittest.main()

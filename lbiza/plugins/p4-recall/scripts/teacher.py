#!/usr/bin/env python3
"""teacher.py: the paid batches of build step 9 (fresh-marketplace.md 1a, 5.2, 5.3, 5.6, 5.7). Never run by a hook.

  p4.py teacher edit-labels [--limit N] [--re-edit] [--second-opinion N] [--max-usd X] [--estimate] [--fake]
      For each task of models/tasks.tsv (newest first; short turns need no teacher, 5.4) the teacher model is sent
      the task and its date, the store's picks (labels-raw.tsv), the repo's entries newer than the teacher's own
      training cutoff that bear on the task (1a), and the candidates (the union of BM25's top 60 and the ranker's
      top 60, each cut to 140 characters). It answers keep or drop for each stored pick and add for any candidate
      that bears on the task, each with a reason. Written: models/label-edits.md (by task: every decision, its
      reason, the teacher's model id, the date) and models/labels.tsv rows with source `store+edited` (kept and
      added picks label 1, dropped picks label 0; `teacher` is the model that answered, `response.model`).
      Without --re-edit a task already edited is skipped; with it only the tasks whose edits came from a different
      teacher are redone, newest first, as many as --max-usd allows.
      --second-opinion N sends N of the batch's tasks (the newest; when the run edits nothing new, the newest of
      the last batch) to Claude Opus 5.5 with the same prompt, and reports the agreement F1 over the positives;
      below 0.65 the batch is held (models/teacher-batches.json), and held rows are not trained on.
  p4.py teacher dictionary [--re-edit] [--max-usd X] [--estimate] [--fake]
      Writes `means:` for the pending entries of store/vocabulary.md, 20 per call, from their `because:` quotes
      alone. Only an entry still pending when its batch is written is filled; an entry the owner wrote or edited is
      never overwritten (`means-by:` records the model, the date and a hash of the meaning it wrote, so an owner's
      later edit is seen; --re-edit redoes only meanings another teacher wrote that nobody has edited since).
  p4.py teacher facts [--limit N] [--max-usd X] [--estimate] [--fake]
      Writes store/facts.md, the file recall serves under `inject: rules-facts` and the one every branch of ap-p4
      left empty because nothing wrote it. For each owner message that asked for a recommendation (a question with
      should / best / which way / recommend, ASK_RE; newest first; one not yet answered, by its `from:`) the model
      is sent the message with the `web_search_20260209` tool and told to find the current official documentation
      and recommend what it says; a second, structured call turns that answer into a claim and a source. The
      source URL is one the search results returned (never one the model only named): an answer that cites none,
      or says the documentation does not settle it, writes nothing (a claim without a source stays out). Written:
      one entry of claim, source, verified (now), by (the model that answered), time (the owner's message), from
      (the message row's id), appended to store/facts.md. A search costs SEARCH_USD on top of the tokens and the
      estimate assumes every allowed search is run.

Cost control, as scripts/session/overrides_suite.py: every request is built first and its input counted with the
API's token counter (`client.messages.count_tokens`, free); the estimate (input at the model's price, plus
OUT_EST output tokens a call, thinking included, at its output price) is refused above --max-usd before anything
is spent; the real spend is read from each `response.usage` and appended to models/spend.json, and a run stops
before a call that would take the real spend past --max-usd. Retries are the SDK's (max_retries). A refusal
(`stop_reason == "refusal"`) is recorded in label-edits.md and the task skipped. `--fake` runs offline with a
deterministic client, for the tests; `--estimate` counts and prints the estimate and calls nothing.

The teacher is `teacher-model:` in models/config.json (default claude-fable-5-1), overridable with --teacher. It
runs with adaptive thinking (Fable runs it always) and structured output (`output_config.format`, a json_schema).
No server-side fallback is enabled: a refusal falls to another model, and labels must carry the teacher that made
them (Opus is not a teacher, design section 2), so a refused task is skipped instead.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import labels as lb  # noqa: E402
import ranker  # noqa: E402
import store as st  # noqa: E402

DEFAULT_TEACHER = "claude-fable-5-1"
SECOND_OPINION = "claude-opus-5-5"
# $ per million tokens, input and output (the claude-api skill's table, cached 2026-10-06; the design's 5.7)
PRICES = {"claude-fable-5-1": (10.0, 50.0), "claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0),
          "claude-haiku-5-5": (0.10, 0.50)}
# Training cutoffs, by model id (1a). Only Claude Opus 5.5's is published in what this repo holds (June 2026, the
# claude-api skill's migration guide); the others are not known here and resolve to the table's oldest known
# cutoff, which errs toward sending more entries as newer. `teacher-cutoff:` in models/config.json, or --cutoff,
# sets it when it is known.
CUTOFFS = {"claude-opus-5-5": "2026-06", "claude-fable-5-1": None, "claude-sonnet-5-5": None,
           "claude-haiku-5-5": None}
CAND_K = 60                   # BM25's top and the ranker's top, each
CAND_CHARS = 140
NEWER_MAX = 12                # entries newer than the cutoff sent with a task
DICT_BATCH = 20
MAX_TOKENS = 16000
EFFORT = "high"
OUT_EST = {"edit-labels": 3000, "dictionary": 4000, "facts": 4000, "facts-extract": 600}   # output tokens a call,
                                                                                            # thinking included (assumed)
SEARCH_MAX_USES = 5           # web searches a facts call may run
SEARCH_USD = 0.01             # per search, on top of the tokens ($10 per 1,000 searches)
# an owner message asking for a recommendation (served_back.ASK_RE), with a question mark
ASK_RE = re.compile(r"(?i)\b(should|better|best|recommend|suggest|which (one|way|approach|option)|what (do|would) you "
                    r"(think|suggest|recommend|do)|or (should|just)|is it (worth|better|ok|fine|right)|do (i|we) need|"
                    r"proper|optimal|correct way)\b")
AGREE_MIN = 0.65              # 5.6: Colab's two teachers agreed at 0.754
EDITS_MD = "label-edits.md"
SPEND = "spend.json"
EDITS_HEAD = ("# Label edits\n\nEvery keep, drop and add the teacher made to the store's labels, by task: the "
              "reason, the teacher's model id (the model that answered) and the date. Written by `p4.py teacher "
              "edit-labels`; the newest batch last. A dropped pick stays in labels-raw.tsv.\n")


# --- prices, config, spend -------------------------------------------------------------------------------

def price(model):
    for k, v in PRICES.items():
        if model == k or model.startswith(k):
            return v
    return PRICES[DEFAULT_TEACHER]


def cost(model, usage):
    p_in, p_out = price(model)
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    return ((getattr(usage, "input_tokens", 0) or 0) * p_in + write * p_in * 1.25 + read * p_in * 0.1
            + (getattr(usage, "output_tokens", 0) or 0) * p_out) / 1e6


def read_config(p4):
    """recall.teacher of p4.json (the retired models/config.json's values when p4.json is absent), under the
    old key names, after setting the teacher's constants from it."""
    import p4conf
    t = p4conf.configure(globals(), p4, "recall.teacher", {"second_opinion": "SECOND_OPINION", "effort": "EFFORT", "max_tokens": "MAX_TOKENS",
                                "agree_min": "AGREE_MIN", "newer_max": "NEWER_MAX", "cand_k": "CAND_K",
                                "dict_batch": "DICT_BATCH"}, write=False)
    return {"teacher-model": t.get("model"), "teacher-cutoff": t.get("cutoff")}


def teacher_of(p4, override=""):
    return override or read_config(p4).get("teacher-model") or DEFAULT_TEACHER


def cutoff_of(model, p4=None, override=""):
    """The model's training cutoff as YYYY-MM: --cutoff, then `teacher-cutoff:` in config.json when `model` is the
    configured teacher, then the table, then the table's oldest known cutoff."""
    if override:
        return override[:7]
    if p4:
        cfg = read_config(p4)
        if cfg.get("teacher-cutoff") and model == (cfg.get("teacher-model") or DEFAULT_TEACHER):
            return str(cfg["teacher-cutoff"])[:7]
    for k, v in CUTOFFS.items():
        if (model == k or model.startswith(k)) and v:
            return v
    return min(v for v in CUTOFFS.values() if v)


def same_teacher(a, b):
    a, b = (a or "").strip(), (b or "").strip()
    return bool(a) and bool(b) and (a == b or a.startswith(b) or b.startswith(a))


def add_spend(p4, step, model, usage, usd, note=""):
    """Append one call's real spend to models/spend.json: {"steps": {step: usd}, "calls": [...]}."""
    path = lb.mpath(p4, SPEND)
    try:
        with open(path, encoding="utf-8") as f:
            cur = json.load(f)
    except (OSError, ValueError):
        cur = {}
    cur.setdefault("steps", {})
    cur.setdefault("calls", [])
    cur["steps"][step] = round(cur["steps"].get(step, 0.0) + usd, 6)
    cur["calls"].append({"time": stamp(), "step": step, "model": model, "note": note,
                         "input": getattr(usage, "input_tokens", 0) or 0,
                         "output": getattr(usage, "output_tokens", 0) or 0, "usd": round(usd, 6)})
    cur["total"] = round(sum(cur["steps"].values()), 6)
    ranker.write_atomic(path, json.dumps(cur, indent=1, ensure_ascii=False) + "\n")


def stamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def clip(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


# --- the clients -----------------------------------------------------------------------------------------

def text_of(content):
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)


FAKE_WORD = re.compile(r"[a-z][a-z0-9_]{3,}")


def fake_words(s):
    return {w for w in FAKE_WORD.findall((s or "").lower()) if w not in st.COMMON}


class FakeClient:
    """Offline and deterministic. edit-labels: a stored pick is kept when it shares a word with the task, dropped
    otherwise; a candidate is added when it shares two (three for an Opus model, so a second opinion can disagree).
    dictionary: a meaning made from the first quote. A task whose text holds FAKE-REFUSE is refused. Counts a token
    per four characters; `answer_as` is the model id it reports (response.model)."""

    def __init__(self, answer_as=None):
        self.messages = self
        self.answer_as = answer_as
        self.created = []
        self.counted = 0

    def count_tokens(self, model, messages, system="", **kw):
        self.counted += 1
        n = len(system if isinstance(system, str) else json.dumps(system))
        n += sum(len(text_of(m["content"])) for m in messages)
        n += len(json.dumps(kw.get("output_config") or {}))
        return SimpleNamespace(input_tokens=n // 4 + 1)

    def create(self, model, messages, system="", max_tokens=0, **kw):
        self.created.append(model)
        prompt = text_of(messages[-1]["content"])
        n_in = self.count_tokens(model, messages, system, **kw).input_tokens
        answered = self.answer_as or model
        if "FAKE-REFUSE" in prompt:
            return SimpleNamespace(content=[], stop_reason="refusal", model=answered,
                                   stop_details=SimpleNamespace(type="refusal", category="fake",
                                                                explanation="the fake client refuses this task"),
                                   usage=SimpleNamespace(input_tokens=n_in, output_tokens=0))
        if kw.get("tools"):
            return self.fake_search(prompt, answered, n_in)
        props = kw["output_config"]["format"]["schema"]["properties"]
        if "picks" in props:
            out = self.fake_edit(prompt, model)
        elif "claim" in props:
            out = self.fake_fact(prompt)
        else:
            out = self.fake_dictionary(prompt)
        body = json.dumps(out)
        return SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking=""),
                                        SimpleNamespace(type="text", text=body)],
                               stop_reason="end_turn", stop_details=None, model=answered,
                               usage=SimpleNamespace(input_tokens=n_in, output_tokens=len(body) // 4 + 200,
                                                     cache_read_input_tokens=0, cache_creation_input_tokens=0))

    @staticmethod
    def fake_edit(prompt, model):
        m = re.search(r"^Task: (.*)$", prompt, re.M)
        task = fake_words(m.group(1) if m else "")
        need = 3 if "opus" in model else 2
        picks, adds = [], []
        for h, line in re.findall(r"^\[([pcn]\d+)\] (.*)$", prompt, re.M):
            shared = len(task & fake_words(line))
            if h.startswith("p"):
                picks.append({"id": h, "decision": "keep" if shared else "drop",
                              "reason": f"shares {shared} words with the task"})
            elif shared >= need:
                adds.append({"id": h, "reason": f"shares {shared} words with the task"})
        return {"picks": picks, "adds": adds}

    @staticmethod
    def fake_search(prompt, answered, n_in):
        """A grounded answer: one web_search_tool_result block naming a documentation page made from the message's
        first words, and a text block citing it; FAKE-UNSETTLED in the message makes the answer say the
        documentation does not settle it."""
        words = sorted(fake_words(prompt.split("\n")[-1]))[:2] or ["docs"]
        url = "https://docs.example.org/" + "-".join(words)
        if "FAKE-UNSETTLED" in prompt:
            text = "The documentation does not settle this; it names no default."
        else:
            text = f"The current documentation says: use the {' '.join(words)} default (version 4.4, 2026-01). "
        hit = SimpleNamespace(type="web_search_result", url=url, title="docs")
        return SimpleNamespace(content=[SimpleNamespace(type="server_tool_use", name="web_search"),
                                        SimpleNamespace(type="web_search_tool_result", content=[hit]),
                                        SimpleNamespace(type="text", text=text,
                                                        citations=[SimpleNamespace(type="web_search_result_location",
                                                                                   url=url)])],
                               stop_reason="end_turn", stop_details=None, model=answered,
                               usage=SimpleNamespace(input_tokens=n_in, output_tokens=len(text) // 4 + 200,
                                                     cache_read_input_tokens=0, cache_creation_input_tokens=0,
                                                     server_tool_use=SimpleNamespace(web_search_requests=1)))

    @staticmethod
    def fake_fact(prompt):
        m = re.search(r"^The current documentation says: (.*?)\s*\(version ([^,]+), ([^)]+)\)", prompt, re.M)
        urls = re.findall(r"https?://\S+", prompt)
        if not m:
            return {"settled": False, "claim": "", "source": urls[0] if urls else "", "as_of": ""}
        return {"settled": True, "claim": m.group(1).rstrip("."), "source": urls[0] if urls else "",
                "as_of": f"{m.group(2)}, {m.group(3)}"}

    @staticmethod
    def fake_dictionary(prompt):
        out = []
        for h, term, rest in re.findall(r"^\[(v\d+)\] term: (.*)\n((?:  because: .*\n?)*)", prompt, re.M):
            q = re.search(r"\"([^\"]+)\"", rest)
            out.append({"id": h, "means": f"(fake) {term} as in: {clip(q.group(1), 60)}" if q else ""})
        return {"entries": out}


def client_for(fake, answer_as=None):
    if fake:
        return FakeClient(answer_as)
    import anthropic
    return anthropic.Anthropic(max_retries=6, timeout=900.0)


def request(model, system, user, schema):
    return {"model": model, "max_tokens": MAX_TOKENS, "system": system,
            "messages": [{"role": "user", "content": user}],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": schema}}}


def count(client, kw):
    extra = {k: kw[k] for k in ("tools",) if k in kw}
    return client.messages.count_tokens(model=kw["model"], messages=kw["messages"], system=kw["system"],
                                        thinking=kw["thinking"], output_config=kw["output_config"],
                                        **extra).input_tokens


def estimate_of(model, n_in, kind):
    p_in, p_out = price(model)
    return (n_in * p_in + OUT_EST[kind] * p_out) / 1e6


class Fatal(Exception):
    pass


def call(client, kw):
    """(status, data, response): status ok | refusal | max_tokens | unparsed | error. A request the API rejects
    as malformed or unauthorized stops the batch (Fatal): every later call would fail the same way."""
    try:
        r = client.messages.create(**kw)
    except Exception as e:  # noqa: BLE001 - the SDK has retried what is retryable
        name = type(e).__name__
        if name in ("BadRequestError", "AuthenticationError", "PermissionDeniedError", "NotFoundError"):
            raise Fatal(f"{name}: {e}") from e
        return "error", {"error": f"{name}: {clip(str(e), 200)}"}, None
    if r.stop_reason == "refusal":
        d = getattr(r, "stop_details", None)
        return "refusal", {"category": getattr(d, "category", None) or "",
                           "explanation": clip(getattr(d, "explanation", "") or "", 200)}, r
    if r.stop_reason == "max_tokens":
        return "max_tokens", {}, r
    text = next((b.text for b in r.content if getattr(b, "type", "") == "text"), "")
    try:
        return "ok", json.loads(text), r
    except ValueError:
        return "unparsed", {"text": clip(text, 200)}, r


# --- edit-labels (5.2) -----------------------------------------------------------------------------------

EDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "picks": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "decision": {"type": "string", "enum": ["keep", "drop"]},
                           "reason": {"type": "string"}},
            "required": ["id", "decision", "reason"], "additionalProperties": False}},
        "adds": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["id", "reason"], "additionalProperties": False}},
    },
    "required": ["picks", "adds"], "additionalProperties": False,
}


def edit_system(cutoff):
    return (
        "You review the training labels of a recall model that is trained on one software repository and its "
        "owner's history. A task is a message the owner sent on a given date. The stored picks are the entries a "
        "mechanical labeler marked as bearing on it; the candidates are other entries a search found. An entry "
        "bears on the task when an assistant answering that message on that date is better off for having it in "
        "front of it: a ruling, correction, fact, earlier message or file the answer depends on or must respect. "
        "Judge as of the task's date, as if your training ran up to that date.\n\n"
        f"Your own training data ends around {cutoff}. The entries marked [newer than your training] record what "
        "the repository learned after that. A stored, verified entry (a fact with verified: or checked:) wins over "
        "your own prior: where it disagrees with what you would assume, the entry is right, and your job is to "
        "judge whether it bears on the task, not to recall the fact yourself. Keep or add such an entry when it "
        "bears on the task, even if your own knowledge would answer differently. When an old and a new version of "
        "the same fact are both present (one supersedes the other, or the same source checked on different "
        "dates), the newer verified one is the positive: keep or add it, and drop the older one.\n\n"
        "Decide keep or drop for every stored pick, and list under adds every candidate or newer entry that bears "
        "on the task and is not already a stored pick. Give each decision a reason in one short plain sentence. "
        "Use the ids in brackets exactly as given.")


def doc_line(d, cutoff, facts):
    """`<date> <kind>: <text>` cut to CAND_CHARS, then the recency fields of a fact, and the newer mark."""
    date = (d.get("time") or "")[:10] or "undated"
    if d.get("file") == "repo":
        text = f"file: {d['show']}"
    elif d.get("file") == "commit":
        text = f"commit: {d['show']}"
    else:
        text = f"{d.get('kind', '')}: {d['show']}"
    s = clip(f"{date} {text}", CAND_CHARS)
    f = facts.get(d["id"])
    if f:
        meta = [f"{k}: {clip(f[k], 40)}" for k in ("verified", "checked", "since", "prior") if f.get(k, "").strip()]
        if meta:
            s += " {" + "; ".join(meta) + "}"
    if newer_than(d, cutoff, facts):
        s += " [newer than your training]"
    return s


def entry_date(d, facts):
    f = facts.get(d["id"]) or {}
    since = (f.get("since") or "").strip()
    return since if re.match(r"\d{4}-\d{2}", since) else (d.get("time") or "")


def newer_than(d, cutoff, facts):
    t = entry_date(d, facts)
    return bool(t) and t[:7] > cutoff


class Context:
    """What every task of a batch shares: the index (with the held entries, for picks made while FREED), the
    ranker, the facts' recency fields, the pool heads."""

    def __init__(self, p4):
        import train
        self.train = train
        self.p4 = p4
        self.idx, _ = st.ensure_index(p4)
        self.hidx = train.with_held(self.idx, p4)
        self.by_id = {d["id"]: d for d in self.hidx["docs"]}
        self.model = ranker.load(lb.mpath(p4, "ranker.json")) or {}
        self.facts = {e.id: e.fields for e in st.load_file(p4, "facts.md")}
        self.extra = {"head140": train.head_tokens(p4)}
        self.tasks = lb.read_tasks(p4)
        self.raw = {}
        for r in lb.read_tsv(lb.mpath(p4, lb.RAW)):
            self.raw.setdefault(r.get("task", ""), []).append(r)


def candidates(ctx, task, pool):
    """[doc] the union of BM25's top CAND_K and the ranker's top CAND_K among the entries the task could have been
    shown (train.eligible); a pool task's from the store's entries alone, as its training candidates are."""
    files = set(st.STORE_FILES) if pool else None
    idx = ctx.hidx if pool else ctx.idx
    xs, _, cand, sc = ctx.train.task_examples(idx, task, set(), limit=0 if pool else ctx.train.CANDIDATES,
                                              files=files, docs_by=ctx.extra)
    if not cand:
        return []
    bm = cand[:CAND_K]
    out = list(bm)
    if ctx.model.get("w"):
        rs = [ranker.score(ctx.model["w"], x) for x in xs]
        top = [cand[k] for k in sorted(range(len(cand)), key=lambda k: (-rs[k], k))[:CAND_K]]
        out += [i for i in top if i not in set(bm)]
    return [idx["docs"][i] for i in out]


def newer_entries(ctx, task, cutoff, exclude):
    """The store's live entries newer than `cutoff` and no later than the task that bear on it (BM25 > 0 on the
    task's words), strongest first, at most NEWER_MAX (1a)."""
    import p4 as cli
    terms = list(dict.fromkeys(ranker.tokens(task["text"])))
    if not terms:
        return []
    scores = cli.bm25_scores(ctx.idx, terms, {})
    docs = ctx.idx["docs"]
    got = []
    for i, s in scores.items():
        d = docs[i]
        if d["file"] not in st.STORE_FILES or d["id"] in exclude or not newer_than(d, cutoff, ctx.facts):
            continue
        t = d.get("time") or ""
        if t and task.get("time") and t[:16] > task["time"][:16]:
            continue
        f = ctx.facts.get(d["id"]) or {}
        marked = bool((f.get("prior") or "").strip() or (f.get("checked") or "").strip())
        got.append((marked, s, d))
    # a fact marked as contradicting a training-era prior, or checked against its source, comes first (3.5)
    got.sort(key=lambda x: (not x[0], -x[1], x[2]["id"]))
    return [d for _, _, d in got[:NEWER_MAX]]


def build_item(ctx, tid, cutoff):
    """{task, handles: {handle: entry id}, picks: [handle], user: str, pool: bool} for one task."""
    task = ctx.tasks[tid]
    raw = ctx.raw.get(tid, [])
    pick_ids = list(dict.fromkeys(r["entry"] for r in raw if str(r.get("label")) == "1"))
    pool = bool(raw) and all(r.get("source") == "pool" for r in raw)
    handles, lines = {}, []
    lines.append(f"Task date: {task.get('time') or 'undated'}")
    lines.append(f"Task: {clip(task.get('text', ''), 2000)}")
    lines.append("")
    lines.append("Stored picks (decide keep or drop for each):")
    picks = []
    for k, eid in enumerate(pick_ids, 1):
        h = f"p{k}"
        handles[h] = eid
        picks.append(h)
        d = ctx.by_id.get(eid)
        lines.append(f"[{h}] " + (doc_line(d, cutoff, ctx.facts) + (f" (state: {d['state']})"
                                                                     if d.get("state", "LIVE") != "LIVE" else "")
                                  if d else f"(an entry no longer indexed: {clip(eid, 100)})"))
    if not picks:
        lines.append("(none)")
    seen = set(pick_ids)
    newer = newer_entries(ctx, task, cutoff, seen)
    lines.append("")
    lines.append(f"Entries newer than your training cutoff ({cutoff}) that bear on the task's words (add any that "
                 "bears on it):")
    for k, d in enumerate(newer, 1):
        h = f"n{k}"
        handles[h] = d["id"]
        seen.add(d["id"])
        lines.append(f"[{h}] " + doc_line(d, cutoff, ctx.facts))
    if not newer:
        lines.append("(none)")
    lines.append("")
    lines.append("Candidates (add any that bears on the task):")
    k = 0
    for d in candidates(ctx, task, pool):
        if d["id"] in seen:
            continue
        seen.add(d["id"])
        k += 1
        h = f"c{k}"
        handles[h] = d["id"]
        lines.append(f"[{h}] " + doc_line(d, cutoff, ctx.facts))
    if not k:
        lines.append("(none)")
    return {"task": tid, "time": task.get("time", ""), "text": task.get("text", ""), "handles": handles,
            "picks": picks, "pool": pool, "user": "\n".join(lines) + "\n"}


def parse_edit(item, data):
    """[(decision, handle, entry id, reason)]: every stored pick decided (one the answer left out is kept, said so),
    then the adds that name a candidate or newer entry; unknown handles are counted in `bad`."""
    out, bad = [], 0
    got = {}
    for p in data.get("picks", []) or []:
        h = str(p.get("id", "")).strip().strip("[]")
        if h in item["picks"] and h not in got and p.get("decision") in ("keep", "drop"):
            got[h] = (p["decision"], clip(p.get("reason", ""), 300))
        elif h not in item["picks"]:
            bad += 1
    for h in item["picks"]:
        d, why = got.get(h, ("keep", "(no decision returned: kept as stored)"))
        out.append((d, h, item["handles"][h], why))
    added = set()
    for a in data.get("adds", []) or []:
        h = str(a.get("id", "")).strip().strip("[]")
        if h in item["handles"] and h not in item["picks"] and h not in added:
            added.add(h)
            out.append(("add", h, item["handles"][h], clip(a.get("reason", ""), 300)))
        elif h not in item["picks"]:
            bad += 1
    return out, bad


def positives(decisions):
    return {e for d, _, e, _ in decisions if d in ("keep", "add")}


def edited_by(p4):
    """{task: teacher} of the store+edited rows in labels.tsv."""
    out = {}
    for r in lb.read_tsv(lb.mpath(p4, lb.TRAIN)):
        if r.get("source") == "store+edited":
            out[r.get("task", "")] = r.get("teacher", "")
    return out


def pick_tasks(p4, ctx, teacher, re_edit, limit):
    """The task ids to edit, newest first: not yet edited, or (re-edit) edited by another teacher."""
    done = edited_by(p4)
    ids = [t for t, r in ctx.tasks.items() if r.get("kind") != "short"]
    if re_edit:
        ids = [t for t in ids if t in done and not same_teacher(done[t], teacher)]
    else:
        ids = [t for t in ids if t not in done]
    ids.sort(key=lambda t: (ctx.tasks[t].get("time", ""), t), reverse=True)
    return ids[:limit] if limit is not None and limit >= 0 else ids


def write_edits_md(p4, bid, item, teacher, when, decisions=None, status="ok", info=None):
    path = lb.mpath(p4, EDITS_MD)
    new = not os.path.exists(path)
    out = [EDITS_HEAD] if new else []
    out.append(f"\n## {item['task']} ({item['time'] or 'undated'})\n")
    out.append(f"task: {clip(item['text'], 300)}\n")
    out.append(f"teacher: {teacher}; edited: {when}; batch: {bid}\n")
    if status != "ok":
        out.append(f"- {status}: " + "; ".join(f"{k} {v}" for k, v in (info or {}).items() if v) + " (task skipped)\n")
    for d, h, eid, why in decisions or []:
        out.append(f"- {d} {eid}: {why}\n")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write("".join(out))


def edit_rows(item, decisions, teacher, when, bid):
    note = f"batch:{bid}" + ("; from:pool" if item["pool"] else "")
    return [{"task": item["task"], "entry": eid, "label": "0" if d == "drop" else "1", "source": "store+edited",
             "weight": "1.0", "time": item["time"], "teacher": teacher, "edited": when, "note": f"{note}; {d}"}
            for d, _, eid, _ in decisions]


def replace_task_rows(p4, rows, tasks):
    """labels.tsv with the store+edited rows of `tasks` replaced by `rows` (every other row as it was)."""
    lb.replace_source(p4, lb.TRAIN, lb.TRAIN_HEAD, "store+edited", rows, tasks=set(tasks))


def f1_agreement(a, b):
    """Micro F1 over (task, entry) positives: {task: set} against {task: set}, on the tasks both answered."""
    common = set(a) & set(b)
    pa = {(t, e) for t in common for e in a[t]}
    pb = {(t, e) for t in common for e in b[t]}
    if not pa and not pb:
        return 1.0 if common else 0.0
    tp = len(pa & pb)
    prec = tp / len(pb) if pb else 0.0
    rec = tp / len(pa) if pa else 0.0
    return 2 * prec * rec / (prec + rec) if prec + rec else 0.0


def save_batch(p4, bid, record):
    cur = lb.read_batches(p4)
    cur.setdefault(bid, {}).update(record)
    ranker.write_atomic(lb.mpath(p4, lb.BATCHES), json.dumps(cur, indent=1, ensure_ascii=False) + "\n")


class Budget:
    def __init__(self, max_usd):
        self.max_usd = max_usd
        self.spent = 0.0

    def room(self, est):
        return self.spent + est <= self.max_usd + 1e-12


def run_calls(p4, client, plan, budget, step, out=print):
    """Send each planned request in order, recording the spend; stop before one that would pass the budget.
    plan: [(key, kw, est)]. Yields (key, status, data, model answered)."""
    for key, kw, est in plan:
        if not budget.room(est):
            out(f"teacher: stopped before {key}: ${budget.spent:.2f} spent, this call's ${est:.3f} would pass "
                f"--max-usd {budget.max_usd}")
            return
        status, data, r = call(client, kw)
        if r is not None:
            usd = cost(kw["model"], r.usage)
            budget.spent += usd
            add_spend(p4, step, getattr(r, "model", kw["model"]) or kw["model"], r.usage, usd, note=key)
        yield key, status, data, (getattr(r, "model", None) or kw["model"]) if r is not None else kw["model"]


def edit_labels(p4, args, client=None, out=print):
    """The edit-labels batch and its second opinion. Returns a summary dict (also for the tests)."""
    teacher = teacher_of(p4, args.teacher)
    cutoff = cutoff_of(teacher, p4, args.cutoff)
    client = client or client_for(args.fake)
    ctx = Context(p4)
    ids = pick_tasks(p4, ctx, teacher, args.re_edit, args.limit)
    system = edit_system(cutoff)
    items = {t: build_item(ctx, t, cutoff) for t in ids}
    plan, n_in = [], 0
    for t in ids:
        kw = request(teacher, system, items[t]["user"], EDIT_SCHEMA)
        c = count(client, kw)
        n_in += c
        plan.append((t, kw, estimate_of(teacher, c, "edit-labels")))
    # the second opinion: this batch's newest tasks, or the last batch's when this run edits nothing new
    so_n = args.second_opinion or 0
    so_ids, so_bid = [], ""
    if so_n:
        if ids:
            so_ids = ids[:so_n]
        else:
            batches = lb.read_batches(p4)
            last = max(batches, key=lambda b: batches[b].get("time", "")) if batches else ""
            if last:
                so_bid = last
                done = edited_by(p4)
                so_ids = [t for t in batches[last].get("tasks", []) if t in done and t in ctx.tasks][:so_n]
        for t in so_ids:
            if t not in items:
                items[t] = build_item(ctx, t, cutoff)
    so_plan, so_in = [], 0
    for t in so_ids:
        kw = request(SECOND_OPINION, system, items[t]["user"], EDIT_SCHEMA)
        c = count(client, kw)
        so_in += c
        so_plan.append((t, kw, estimate_of(SECOND_OPINION, c, "edit-labels")))
    est = sum(e for _, _, e in plan)
    so_est = sum(e for _, _, e in so_plan)
    summary = {"teacher": teacher, "cutoff": cutoff, "tasks": len(ids), "estimate": est, "so_tasks": len(so_ids),
               "so_estimate": so_est, "edited": 0, "refused": 0, "failed": 0, "spent": 0.0, "f1": None,
               "status": "", "batch": ""}
    summary.update(input_tokens=n_in, so_input_tokens=so_in)
    out(f"teacher edit-labels: {len(ids)} tasks for {teacher} (cutoff {cutoff}), {n_in:,} input tokens + "
        f"{OUT_EST['edit-labels']:,} output a call, estimated ${est:.2f}"
        + (f"; second opinion on {len(so_ids)} tasks with {SECOND_OPINION}, {so_in:,} input tokens, estimated "
           f"${so_est:.2f}" if so_n else "")
        + f"; --max-usd {args.max_usd}")
    if args.estimate:
        summary["status"] = "estimate"
        return summary
    if est + so_est > args.max_usd:
        if args.re_edit and plan:
            # 1a: a teacher change re-edits the newest tasks first, as many as the budget allows
            keep, run = [], so_est
            for p in plan:
                if run + p[2] > args.max_usd:
                    break
                keep.append(p)
                run += p[2]
            out(f"teacher: --re-edit within --max-usd: the newest {len(keep)} of {len(plan)} tasks")
            plan = keep
        else:
            summary["status"] = "refused"
            out(f"teacher: estimated ${est + so_est:.2f} is above --max-usd {args.max_usd}; nothing was sent")
            return summary
    budget = Budget(args.max_usd)
    bid = (args.batch or f"{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-{teacher}") if plan else ""
    when = args.now or stamp()
    batch_tasks, answered_by = [], set()
    try:
        for t, status, data, model in run_calls(p4, client, plan, budget, f"edit-labels {bid}", out):
            item = items[t]
            if status != "ok":
                summary["refused" if status == "refusal" else "failed"] += 1
                write_edits_md(p4, bid, item, model, when, status=status, info=data)
                out(f"  {t}: {status} {data.get('category', '') or data.get('error', '')}".rstrip())
                continue
            decisions, bad = parse_edit(item, data)
            replace_task_rows(p4, edit_rows(item, decisions, model, when, bid), [t])
            write_edits_md(p4, bid, item, model, when, decisions)
            batch_tasks.append(t)
            answered_by.add(model)
            summary["edited"] += 1
            if bad:
                out(f"  {t}: {bad} ids in the answer named nothing sent; ignored")
    except Fatal as e:
        out(f"teacher: stopped, the API rejected the request: {e}")
        summary["status"] = "fatal"
    if bid and batch_tasks:
        save_batch(p4, bid, {"teacher": sorted(answered_by), "configured": teacher, "cutoff": cutoff,
                             "time": when, "tasks": batch_tasks, "status": "ok", "kind": "edit-labels"})
        summary["batch"] = bid
    summary["spent"] = budget.spent
    # the second opinion (5.6)
    if so_plan and summary["status"] != "fatal":
        target = bid if batch_tasks else so_bid
        done_now = {}
        for r in lb.read_tsv(lb.mpath(p4, lb.TRAIN)):
            if r.get("source") == "store+edited" and r.get("label") == "1":
                done_now.setdefault(r["task"], set()).add(r["entry"])
        theirs = {}
        so_plan = [p for p in so_plan if p[0] in (batch_tasks if batch_tasks else so_ids)]
        try:
            for t, status, data, model in run_calls(p4, client, so_plan, budget, f"second opinion {target}", out):
                if status != "ok":
                    out(f"  second opinion {t}: {status}")
                    continue
                decisions, _ = parse_edit(items[t], data)
                theirs[t] = positives(decisions)
        except Fatal as e:
            out(f"teacher: second opinion stopped, the API rejected the request: {e}")
        ours = {t: done_now.get(t, set()) for t in theirs}
        if theirs and target:
            f1 = f1_agreement(ours, theirs)
            held = f1 < AGREE_MIN
            rec = {"second_opinion": {"model": SECOND_OPINION, "tasks": sorted(theirs), "f1": round(f1, 4),
                                      "time": stamp()}}
            if held:
                rec.update(status="held", why=f"second opinion F1 {f1:.3f} below {AGREE_MIN} ({SECOND_OPINION}, "
                                              f"{len(theirs)} tasks)")
            save_batch(p4, target, rec)
            with open(lb.mpath(p4, EDITS_MD), "a", encoding="utf-8", newline="\n") as f:
                f.write(f"\nbatch {target}: second opinion from {SECOND_OPINION} on {len(theirs)} tasks, agreement F1 "
                        f"{f1:.3f}" + (f" (below {AGREE_MIN}: the batch is held for the owner)\n" if held else "\n"))
            summary["f1"], summary["held"] = f1, held
            out(f"teacher: second opinion F1 {f1:.3f} over {len(theirs)} tasks"
                + (f": below {AGREE_MIN}, batch {target} held" if held else f" (at or above {AGREE_MIN})"))
    summary["spent"] = budget.spent
    summary["status"] = summary["status"] or "done"
    out(f"teacher edit-labels: {summary['edited']} edited, {summary['refused']} refused, {summary['failed']} failed; "
        f"${budget.spent:.2f} spent (models/{SPEND})")
    return summary


# --- dictionary (5.3) ------------------------------------------------------------------------------------

DICT_SCHEMA = {
    "type": "object",
    "properties": {"entries": {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "string"}, "means": {"type": "string"}},
        "required": ["id", "means"], "additionalProperties": False}}},
    "required": ["entries"], "additionalProperties": False,
}

DICT_SYSTEM = (
    "You write the meanings in a repository owner's vocabulary dictionary. Each term below once caused a "
    "misreading the owner had to correct; its because: lines quote the exchange that proves it: what the owner "
    "wrote, how it was read, and what the owner wrote next. From those quotes alone, write what the term meant to "
    "the owner, as one clause, in the owner's own words where the follow-up supplies them. Do not guess beyond the "
    "quotes: when they do not show what the term meant, return an empty string for it. Use the ids in brackets "
    "exactly as given.")


def means_hash(text):
    return hashlib.sha1(re.sub(r"\s+", " ", text or "").strip().encode("utf-8")).hexdigest()[:8]


def means_by(e):
    """(model, date, hash) of an entry's `means-by:` line, or None."""
    v = (e.fields.get("means-by") or "").split()
    return (v[0], " ".join(v[1:-1]), v[-1]) if len(v) >= 3 else None


def owner_entry(e):
    return "owner" in (e.fields.get("source") or "").lower()


def dict_targets(p4, teacher, re_edit):
    """The vocabulary entries to write: pending ones (never an owner's); with --re-edit also meanings another
    teacher wrote that are unchanged since (their hash still matches)."""
    out = []
    for e in st.load_file(p4, st.VOCABULARY):
        if e.head != "term" or owner_entry(e):
            continue
        means = (e.fields.get("means") or "").strip()
        if not means or means.startswith("(pending"):
            out.append(e)
        elif re_edit:
            mb = means_by(e)
            if mb and not same_teacher(mb[0], teacher) and mb[2] == means_hash(means):
                out.append(e)
    return out


def dict_user(batch):
    lines, handles = [], {}
    for k, e in enumerate(batch, 1):
        h = f"v{k}"
        handles[h] = e
        lines.append(f"[{h}] term: {e.value.strip()}")
        for b in e.all("because"):
            lines.append(f"  because: {clip(b, 600)}")
    return "\n".join(lines) + "\n", handles


def write_meanings(p4, answers, teacher, when, re_edit=False):
    """Fill `means:` for {(line, term, old means): new means}, re-reading vocabulary.md first: an entry is written
    only when it still stands at that line with that term and the meaning it had when the batch was built (so an
    owner's edit made meanwhile wins), and never when its source is the owner's. Only the entry's `means:` and
    `means-by:` lines change. Returns the count written."""
    path = os.path.join(st.store_dir(p4), st.VOCABULARY)
    text = st.read_text(path)
    parsed = [e for e in st.parse(text, st.VOCABULARY) if e.head == "term"]
    ls = text.split("\n")
    n = 0
    found = []
    for (line, term, old), means in answers.items():
        # the entry by its term, nearest the line it stood at (an earlier batch's write may have moved it)
        same = [e for e in parsed if e.value.strip() == term]
        if same:
            found.append((min(same, key=lambda e: abs(e.line - line)), old, means))
    for e, old, means in sorted(found, key=lambda x: -x[0].line):
        line = e.line
        if owner_entry(e):
            continue
        cur = (e.fields.get("means") or "").strip()
        if cur != old:
            continue                                   # edited since the batch was built: the edit stands
        if cur and not cur.startswith("(pending"):
            mb = means_by(e)
            if not re_edit or not mb or mb[2] != means_hash(cur):
                continue                               # a meaning someone wrote or edited by hand
        means = re.sub(r"\s+", " ", means).strip()
        if not means:
            continue
        i = line - 1
        j = i + 1
        end = j
        while end < len(ls) and (ls[end].startswith("  ") or ls[end].startswith(st.CONT_PREFIX)):
            end += 1
        block = ls[j:end]
        new_by = f"  means-by: {teacher} {when} {means_hash(means)}"
        mi = next((k for k, l in enumerate(block) if re.match(r"^  means:", l)), None)
        if mi is None:
            block.insert(0, f"  means: {means}")
            mi = 0
        else:
            k = mi + 1
            while k < len(block) and block[k].startswith(st.CONT_PREFIX):
                k += 1
            block[mi:k] = [f"  means: {means}"]
        bi = next((k for k, l in enumerate(block) if re.match(r"^  means-by:", l)), None)
        if bi is None:
            block.insert(mi + 1, new_by)
        else:
            block[bi] = new_by
        ls[j:end] = block
        n += 1
    if n:
        ranker.write_atomic(path, "\n".join(ls))
    return n


def dictionary(p4, args, client=None, out=print):
    teacher = teacher_of(p4, args.teacher)
    client = client or client_for(args.fake)
    targets = dict_targets(p4, teacher, args.re_edit)
    batches = [targets[k:k + DICT_BATCH] for k in range(0, len(targets), DICT_BATCH)]
    if args.limit is not None and args.limit >= 0:
        batches = batches[:args.limit]
    plan, users, n_in = [], {}, 0
    for k, b in enumerate(batches):
        user, handles = dict_user(b)
        kw = request(teacher, DICT_SYSTEM, user, DICT_SCHEMA)
        users[f"b{k}"] = handles
        c = count(client, kw)
        n_in += c
        plan.append((f"b{k}", kw, estimate_of(teacher, c, "dictionary")))
    est = sum(e for _, _, e in plan)
    summary = {"teacher": teacher, "entries": sum(len(b) for b in batches), "calls": len(plan), "estimate": est,
               "written": 0, "refused": 0, "failed": 0, "spent": 0.0, "status": ""}
    summary["input_tokens"] = n_in
    out(f"teacher dictionary: {summary['entries']} entries in {len(plan)} calls for {teacher}, {n_in:,} input tokens "
        f"+ {OUT_EST['dictionary']:,} output a call, estimated ${est:.2f}; --max-usd {args.max_usd}")
    if args.estimate:
        summary["status"] = "estimate"
        return summary
    if est > args.max_usd:
        summary["status"] = "refused"
        out(f"teacher: estimated ${est:.2f} is above --max-usd {args.max_usd}; nothing was sent")
        return summary
    budget = Budget(args.max_usd)
    when = args.now or stamp()
    step = f"dictionary {datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-{teacher}"
    try:
        for key, status, data, model in run_calls(p4, client, plan, budget, step, out):
            if status != "ok":
                summary["refused" if status == "refusal" else "failed"] += 1
                out(f"  {key}: {status} {data.get('category', '') or data.get('error', '')}".rstrip())
                continue
            answers = {}
            for a in data.get("entries", []) or []:
                e = users[key].get(str(a.get("id", "")).strip().strip("[]"))
                if e is not None:
                    answers[(e.line, e.value.strip(), (e.fields.get("means") or "").strip())] = a.get("means", "")
            summary["written"] += write_meanings(p4, answers, model, when, args.re_edit)
    except Fatal as e:
        out(f"teacher: stopped, the API rejected the request: {e}")
        summary["status"] = "fatal"
    summary["spent"] = budget.spent
    summary["status"] = summary["status"] or "done"
    out(f"teacher dictionary: {summary['written']} meanings written, {summary['refused']} batches refused, "
        f"{summary['failed']} failed; ${budget.spent:.2f} spent (models/{SPEND})")
    return summary


# --- facts (the file recall serves under inject: rules-facts; nothing else writes it) -------------------------

FACTS_SYSTEM = (
    "You are answering a software project's owner, and you must not answer from memory. Search for the current "
    "official documentation or primary source for what the message asks about (the project's own docs, the "
    "vendor's reference, the standard, the release notes), read it, and recommend what it says, in two or three "
    "sentences. Quote the documented approach's date or version. Cite every source you used by URL. When the "
    "documentation does not settle it, say so instead of recommending.")

FACT_EXTRACT_SYSTEM = "You extract structured fields from text; you add nothing."

FACT_SCHEMA = {
    "type": "object",
    "properties": {
        "settled": {"type": "boolean", "description": "true when the answer recommends from documentation it read"},
        "claim": {"type": "string", "description": "one sentence stating the documented fact, written so it holds "
                                                   "without the conversation; empty when not settled"},
        "source": {"type": "string", "description": "the URL of the source the claim rests on, from the answer"},
        "as_of": {"type": "string", "description": "the date or version the documentation is current to"},
    },
    "required": ["settled", "claim", "source", "as_of"], "additionalProperties": False,
}


def asks_recommendation(text):
    return "?" in (text or "") and bool(ASK_RE.search(text))


def fact_targets(p4, limit=None, files=None):
    """The owner message rows that asked for a recommendation and have no facts.md entry pointing at them
    (`from:`), newest first; `limit` keeps the newest N."""
    files = files if files is not None else st.load_store(p4)
    done = {e.fields.get("from", "").strip() for e in files.get("facts.md", [])}
    rows = []
    for rel, entries in files.items():
        if not rel.startswith(st.MESSAGES + "/"):
            continue
        for e in entries:
            fp = st.unquote(e.fields.get("fingerprint", e.value))
            if st.owner_message(e, fp) and st.completed(e) and asks_recommendation(fp) and e.id not in done:
                rows.append(e)
    rows.sort(key=lambda e: (e.time, e.id), reverse=True)
    return rows[:limit] if limit is not None and limit >= 0 else rows


def search_request(model, user):
    return {"model": model, "max_tokens": MAX_TOKENS, "system": FACTS_SYSTEM,
            "messages": [{"role": "user", "content": user}],
            "tools": [{"type": "web_search_20260209", "name": "web_search", "max_uses": SEARCH_MAX_USES}],
            "thinking": {"type": "adaptive"}, "output_config": {"effort": EFFORT}}


def search_call(client, kw):
    """(status, text, urls, searches, responses): the answer's text, the URLs the search results returned (tool
    result blocks and citations: never a URL the model only named), the searches run. A pause_turn is continued,
    up to three times."""
    messages = list(kw["messages"])
    text, urls, searches, responses = "", [], 0, []
    for _ in range(3):
        try:
            r = client.messages.create(**{**kw, "messages": messages})
        except Exception as e:  # noqa: BLE001 - the SDK has retried what is retryable
            name = type(e).__name__
            if name in ("BadRequestError", "AuthenticationError", "PermissionDeniedError", "NotFoundError"):
                raise Fatal(f"{name}: {e}") from e
            return "error", f"{name}: {clip(str(e), 200)}", urls, searches, responses
        responses.append(r)
        for b in r.content:
            kind = getattr(b, "type", "")
            if kind == "web_search_tool_result":
                content = getattr(b, "content", None)
                if isinstance(content, list):
                    searches += 1
                    urls += [getattr(x, "url", "") for x in content if getattr(x, "url", "")]
            elif kind == "text":
                text += getattr(b, "text", "") or ""
                for cit in getattr(b, "citations", None) or []:
                    if getattr(cit, "url", ""):
                        urls.append(cit.url)
        if r.stop_reason == "refusal":
            return "refusal", text, urls, searches, responses
        if r.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": r.content})
    return "ok", text, list(dict.fromkeys(urls)), searches, responses


def fact_entry(claim, source, when, model, row):
    return [("claim", clip(claim, 600)), ("source", source), ("verified", when), ("by", model),
            ("time", row.time), ("from", row.id)]


def append_facts(p4, entries):
    path = os.path.join(st.store_dir(p4), "facts.md")
    text = st.read_text(path) if os.path.exists(path) else st.render("facts.md", [])
    text = text.rstrip("\n") + "".join("\n\n" + st.format_entry(p) for p in entries) + "\n"
    ranker.write_atomic(path, text)


def facts(p4, args, client=None, out=print):
    """The facts batch. Returns a summary dict (also for the tests)."""
    teacher = teacher_of(p4, args.teacher)
    client = client or client_for(args.fake)
    rows = fact_targets(p4, args.limit)
    plan, n_in = [], 0
    for e in rows:
        fp = st.unquote(e.fields.get("fingerprint", e.value))
        when_asked = e.time
        user = f"The owner's message ({when_asked}):\n\n{fp}"
        kw = search_request(teacher, user)
        c = count(client, kw)
        n_in += c
        est = (estimate_of(teacher, c, "facts") + SEARCH_USD * SEARCH_MAX_USES
               + estimate_of(teacher, c + 2000, "facts-extract"))
        plan.append((e, kw, est))
    est = sum(x for _, _, x in plan)
    summary = {"teacher": teacher, "tasks": len(rows), "estimate": est, "input_tokens": n_in, "written": 0,
               "unsettled": 0, "unsourced": 0, "refused": 0, "failed": 0, "searches": 0, "spent": 0.0, "status": ""}
    out(f"teacher facts: {len(rows)} recommendation questions for {teacher}, {n_in:,} input tokens + "
        f"{OUT_EST['facts']:,} output a call, up to {SEARCH_MAX_USES} searches each at ${SEARCH_USD}, plus one "
        f"extraction call; estimated ${est:.2f}; --max-usd {args.max_usd}")
    if args.estimate:
        summary["status"] = "estimate"
        return summary
    if est > args.max_usd:
        summary["status"] = "refused"
        out(f"teacher: estimated ${est:.2f} is above --max-usd {args.max_usd}; nothing was sent")
        return summary
    budget = Budget(args.max_usd)
    when = args.now or stamp()
    step = f"facts {datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-{teacher}"
    try:
        for e, kw, est_one in plan:
            if not budget.room(est_one):
                out(f"teacher: stopped before {e.id}: ${budget.spent:.2f} spent, this call's ${est_one:.3f} would "
                    f"pass --max-usd {args.max_usd}")
                break
            status, text, urls, searches, responses = search_call(client, kw)
            model = teacher
            for r in responses:
                usd = cost(kw["model"], r.usage) + SEARCH_USD * searches / max(1, len(responses))
                budget.spent += usd
                model = getattr(r, "model", None) or teacher
                add_spend(p4, step, model, r.usage, usd, note=f"{e.id}; {searches} searches")
            summary["searches"] += searches
            if status != "ok":
                summary["refused" if status == "refusal" else "failed"] += 1
                out(f"  {e.id}: {status} {text if status == 'error' else ''}".rstrip())
                continue
            if not urls:
                summary["unsourced"] += 1
                out(f"  {e.id}: the search returned no source; nothing written")
                continue
            ekw = request(teacher, FACT_EXTRACT_SYSTEM,
                          "Below is an agent's answer written after searching documentation, then the URLs the "
                          "search returned. Put it into the schema: settled (it recommends from documentation it "
                          "read), the claim as one sentence that holds without this conversation, the source URL it "
                          "rests on (one of the URLs listed), the date or version it says the documentation is "
                          f"current to.\n\nAnswer:\n{text}\n\nURLs the search returned:\n" + "\n".join(urls),
                          FACT_SCHEMA)
            xstatus, data, xr = call(client, ekw)
            if xr is not None:
                usd = cost(ekw["model"], xr.usage)
                budget.spent += usd
                add_spend(p4, step, getattr(xr, "model", None) or teacher, xr.usage, usd, note=f"{e.id}; extract")
            if xstatus != "ok":
                summary["refused" if xstatus == "refusal" else "failed"] += 1
                out(f"  {e.id}: extraction {xstatus}")
                continue
            claim = (data.get("claim") or "").strip()
            if not data.get("settled") or not claim:
                summary["unsettled"] += 1
                out(f"  {e.id}: the documentation does not settle it; nothing written")
                continue
            source = data.get("source", "").strip()
            if source not in urls:
                source = urls[0]
            append_facts(p4, [fact_entry(claim, source, when, model, e)])
            summary["written"] += 1
            out(f"  {e.id}: {clip(claim, 100)} ({source})")
    except Fatal as ex:
        out(f"teacher: stopped, the API rejected the request: {ex}")
        summary["status"] = "fatal"
    summary["spent"] = budget.spent
    summary["status"] = summary["status"] or "done"
    out(f"teacher facts: {summary['written']} facts written, {summary['unsettled']} unsettled, "
        f"{summary['unsourced']} unsourced, {summary['refused']} refused, {summary['failed']} failed; "
        f"{summary['searches']} searches; ${budget.spent:.2f} spent (models/{SPEND})")
    return summary


# --- the command line ------------------------------------------------------------------------------------

def parser():
    ap = argparse.ArgumentParser(prog="p4.py teacher", description="the paid batches (build step 9)")
    ap.add_argument("action", choices=("edit-labels", "dictionary", "facts", "extract"))
    ap.add_argument("--p4")
    ap.add_argument("--limit", type=int, default=None,
                    help="edit-labels: the newest N tasks; dictionary: the first N batches of 20; facts: the newest "
                         "N recommendation questions")
    ap.add_argument("--re-edit", action="store_true")
    ap.add_argument("--second-opinion", type=int, default=0, metavar="N")
    ap.add_argument("--max-usd", type=float, default=1.0)
    ap.add_argument("--estimate", action="store_true", help="count the input, print the estimate, send nothing")
    ap.add_argument("--fake", action="store_true", help="the offline deterministic client")
    ap.add_argument("--teacher", default="", help="override models/config.json teacher-model")
    ap.add_argument("--cutoff", default="", help="the teacher's training cutoff, YYYY-MM")
    ap.add_argument("--batch", default="", help=argparse.SUPPRESS)
    ap.add_argument("--now", default="", help=argparse.SUPPRESS)
    return ap


def main(argv=None, p4=None):
    args = parser().parse_args(argv)
    p4 = st.find_p4(args.p4 or p4)
    if not p4 or not os.path.isdir(p4):
        print("p4: no .claude/p4 directory found", file=sys.stderr)
        return 1
    read_config(p4)
    if args.action == "extract":
        print("p4.py teacher extract: not built yet (build step 10)", file=sys.stderr)
        return 2
    if not args.fake and not args.estimate and not (os.environ.get("ANTHROPIC_API_KEY")
                                                    or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                                                    or os.environ.get("ANTHROPIC_PROFILE")):
        print("teacher: no ANTHROPIC_API_KEY in the environment; the SDK will try a stored profile", file=sys.stderr)
    s = {"edit-labels": edit_labels, "dictionary": dictionary, "facts": facts}[args.action](p4, args)
    return 3 if s["status"] in ("refused", "fatal") else 0


if __name__ == "__main__":
    sys.exit(main())

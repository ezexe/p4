# The plan-planner evidence checker: every link and fenced snippet of a plan's "# <PLAN>: every layer in source"
# section checked against the working tree as it stands now (the Doctrine Operationalization Phase, lifecycle "Completing a plan",
# flight-ops Landing 2).
# For each bullet: every [text](../../../path:a-b) link (or path#La-Lb) must name a file that exists, and a range
# inside it; every fence under the bullet must appear, line for line (whitespace-trimmed), in one of the bullet's
# linked files, and the range it is found at is printed beside the range cited. Diff fences and lines holding "..."
# are not matched (a diff is not the tree's text, an ellipsis quotes a part).
# Run from the repository root: python3 -I <plan-planner skill dir>/scripts/check_evidence.py <plan.md> .
# Prints MISSING, RANGE, GREPLINE, NOFENCE or MOVED per miss, then "done: N finding(s)"; exit 1 when N > 0.
# A plan with no such section prints "done: 0 finding(s) (no evidence section)" and exits 0.
import re
import sys
from pathlib import Path

LINK = re.compile(r"\]\((?:\.\./)+([^):#]+?)(?::(\d+)(?:-(\d+))?|#L(\d+)(?:-L?(\d+))?)?\)")


def main() -> int:
    plan = Path(sys.argv[1])
    root = Path(sys.argv[2])
    lines = plan.read_text(encoding="utf-8").splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("# ") and l.endswith(": every layer in source")), None)
    if start is None:
        print("done: 0 finding(s) (no evidence section)")
        return 0
    cache: dict[Path, list[str]] = {}

    def read(p: Path) -> list[str] | None:
        if p not in cache:
            cache[p] = p.read_text(encoding="utf-8", errors="replace").splitlines() if p.is_file() else None
        return cache[p]

    bad = 0
    links: list[tuple[Path, int | None, int | None]] = []
    bullet = ""
    i = start
    while i < len(lines):
        line = lines[i]
        if line.startswith("- ") or line.startswith("## "):
            bullet = line[:90]
            links = []
            for m in LINK.finditer(line):
                rel = m.group(1)
                if rel.startswith("http"):
                    continue
                p = root / rel
                a = int(m.group(2) or m.group(4)) if (m.group(2) or m.group(4)) else None
                b = int(m.group(3) or m.group(5)) if (m.group(3) or m.group(5)) else a
                body = read(p)
                if body is None:
                    print(f"MISSING  {rel}  <- {bullet}")
                    bad += 1
                    continue
                if b is not None and b > len(body):
                    print(f"RANGE    {rel}:{a}-{b} past {len(body)} lines  <- {bullet}")
                    bad += 1
                links.append((p, a, b))
        elif line.startswith("```"):
            lang = line[3:].strip()
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            snippet = [s.strip() for s in lines[i + 1:j] if s.strip()]
            i = j
            if lang == "text":
                # grep-style lines, "path:N: text": the file's line N must read the text
                for s in snippet:
                    g = re.match(r"([\w./\\-]+\.\w+):(\d+): (.*)$", s)
                    if not g or g.group(3).endswith("..."):
                        continue
                    rel, n, want = g.group(1), int(g.group(2)), g.group(3).strip()
                    cands = [root / rel] + [p for p, _, _ in links if p.name == Path(rel).name]
                    body = next((read(p) for p in cands if read(p) is not None), None)
                    if body is None:
                        print(f"MISSING  {rel} (text fence)  <- {bullet}")
                        bad += 1
                    elif n > len(body) or body[n - 1].strip() != want:
                        at = [k + 1 for k, t in enumerate(body) if t.strip() == want]
                        print(f"GREPLINE {rel}:{n} now at {at or 'nowhere'}  <- {bullet}")
                        bad += 1
                i += 1
                continue
            if lang == "diff" or not snippet or any("..." in s for s in snippet):
                i += 1
                continue
            found = None
            for p, a, b in links:
                body = [s.strip() for s in read(p)]
                n = len(snippet)
                for k in range(len(body) - n + 1):
                    if body[k] != snippet[0]:
                        continue
                    # blank lines in the file may sit between snippet lines
                    q, ok = k, True
                    for s in snippet:
                        while q < len(body) and not body[q]:
                            q += 1
                        if q >= len(body) or body[q] != s:
                            ok = False
                            break
                        q += 1
                    if ok:
                        found = (p, k + 1, q, a, b)
                        break
                if found:
                    break
            if not found:
                print(f"NOFENCE  {lang} fence at plan:{i}  first: {snippet[0][:70]!r}  <- {bullet}")
                bad += 1
            else:
                p, fa, fb, a, b = found
                cited = [(x, y) for q, x, y in links if q == p]
                if a is not None and not any(x is None or (x <= fa and fb <= y) for x, y in cited):
                    print(f"MOVED    {p.relative_to(root)} cited {a}-{b}, found {fa}-{fb}  <- {bullet}")
                    bad += 1
        i += 1
    print(f"done: {bad} finding(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

"""node.py: the content words two texts share.

phi.py imports it whenever it runs. The start background phi.py builds lists the notes of the sessions above and
the last turns of the siblings in the order `by_overlap` gives: the most content words shared with the session's
task first. node.py uses the standard library only.
"""

import re


WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
STOP = frozenset("""the and for that this with from are was were not but its his her their them they you your our
into onto than then when what which who whom how why where there here have has had been being out off any all each
every one two own same such only also just very more most less over under again once both some none nor too can
will would should could may might must shall per via about after before between while during without within upon
those these ever never always still yet already itself session sessions task""".split())


def words(text):
    """The content words of a text: lower case, three letters or more, not a common word."""
    return {w for w in (m.lower() for m in WORD.findall(str(text or ""))) if len(w) >= 3 and w not in STOP}


def by_overlap(items, task, key=lambda x: x):
    """`items` ordered by how many content words each shares with `task`, most first; ties keep their order. With
    no task the order is kept."""
    want = words(task)
    if not want:
        return list(items)
    scored = [(-len(words(key(x)) & want), k, x) for k, x in enumerate(items)]
    return [x for _, _, x in sorted(scored, key=lambda t: (t[0], t[1]))]



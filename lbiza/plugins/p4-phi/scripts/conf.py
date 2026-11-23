"""conf.py: `phi.py conf`, one setting of the store's p4.json read or written by a command.

A session's file tools write nothing under `.claude` without a prompt, so a setting a conversation with ezexe settled
is written here, checked as its reader takes it, and read back. The keys are p4conf.env_keys(): every default of
the `phi` section of p4.json and each key of it that is read only when a project sets it. A key of another section,
`scratchpad` or `temportal`, is set in p4.json by hand. A key with a command of its own is left to that command, and a
key of Claude Code's own settings is no key of p4.json.
"""

import json

import p4conf

OWN = {"phi.upkeep": "`phi.py upkeep on` or `off`",
       "phi.cards": "`phi.py cards on <id>`, behind its approval card"}


def _text(v, default):
    unset = v is p4conf._NONE or (default is p4conf._NONE and v is None)
    return "unset" if unset else json.dumps(v, ensure_ascii=False)


def show(store, key=""):
    """One line for each key, or for `key` alone: its value as p4.json holds it, `unset` for a key no file sets, and
    the variable a person set that is read ahead of it."""
    held = p4conf.load(store, write=False, warn=False, env=False)
    person = p4conf.person_env(store, warn=False)
    out = []
    for k, default in p4conf.env_keys().items():
        if key and k != key:
            continue
        ahead = f", and the variable {p4conf.env_name(k)} a person set is read ahead of it" if k in person else ""
        out.append(f"{k} = {_text(p4conf._get(held, k), default)}{ahead}")
    return out


def _refused(key):
    if key in OWN:
        return f"phi: {key} is set by {OWN[key]}, and nothing is written"
    if key not in p4conf.env_keys():
        return (f"phi: {key} is no setting of p4.json that p4 reads, and nothing is written: `phi.py conf` lists "
                f"them, and a key of Claude Code's own settings is ezexe's to write")
    return ""


def _kept(store, key, value):
    p4conf.set_key(store, key, value)
    return 0, show(store, key)


def put(store, key, text):
    """`key` set to what `text` reads as for that key. Returns (the exit status, the lines to print)."""
    why = _refused(key)
    if why:
        return 2, [why]
    value = p4conf.env_value(key, text, p4conf.env_keys()[key])
    if value is p4conf._NONE or value is p4conf._BAD:
        return 2, [f"phi: {text!r} does not fit {key}, and nothing is written"]
    return _kept(store, key, value)


def unset(store, key):
    """`key` back at its default, or at `null` for a key read only when set, which each of those keys' readers
    takes as unset, as `phi.py cards off` writes `phi.cards`."""
    why = _refused(key)
    if why:
        return 2, [why]
    default = p4conf.env_keys()[key]
    return _kept(store, key, None if default is p4conf._NONE else default)

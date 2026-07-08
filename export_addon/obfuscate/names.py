"""Deterministic short-name generation and whole-token text replacement."""

import hashlib
import re


def _hash(*parts):
    return hashlib.sha1("\0".join(parts).encode("utf-8")).hexdigest()


def unique_name(seed, used, length=4):
    """A short deterministic token derived from ``seed``, unique within
    ``used`` (a set we add to)."""
    digest = _hash(seed)
    n = length
    while n <= len(digest):
        cand = digest[:n]
        if cand not in used:
            used.add(cand)
            return cand
        n += 1
    i = 0  # astronomically unlikely
    while True:
        cand = digest + format(i, "x")
        if cand not in used:
            used.add(cand)
            return cand
        i += 1


def make_token_replacer(mapping, left, right):
    """A function that replaces each whole-token key of ``mapping`` in a string.

    ``left``/``right`` are character-class bodies used as negative look-around so
    only complete tokens are replaced (e.g. ``a:b`` is not matched inside
    ``a:bc``)."""
    if not mapping:
        return lambda text: text
    keys = sorted(mapping, key=len, reverse=True)
    pat = re.compile(
        r"(?<![%s])(?:%s)(?![%s])"
        % (left, "|".join(re.escape(k) for k in keys), right)
    )
    return lambda text: pat.sub(lambda m: mapping[m.group(0)], text)

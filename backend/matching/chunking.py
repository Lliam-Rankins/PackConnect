"""Split a profile field into short phrases so each can be embedded on its own."""

import re

# ; , . newlines and bullet characters separate phrases.
_SEPARATORS = re.compile(r"[;,.\n\r•·▪◦‣●]+")
_EDGE_MARKS = " \t-*–—"


def split_phrases(text, max_phrases=20, max_chars=200):
    """Distinct non-empty phrases of `text` in order, each cut to max_chars, at most max_phrases."""
    phrases, seen = [], set()
    for part in _SEPARATORS.split(text or ""):
        phrase = part.strip().lstrip(_EDGE_MARKS)[:max_chars].strip()
        key = phrase.lower()
        if not phrase or key in seen:
            continue
        seen.add(key)
        phrases.append(phrase)
        if len(phrases) == max_phrases:
            break
    return phrases

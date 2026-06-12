"""Lightweight profanity filter for user handles (v2.5-WP35).

Best-effort filter. Not a security boundary. Admin moderation via
PATCH /admin/users/:id/handle is the escalation path.

Approach: simple substring match against a conservative blocklist of
obvious slurs and expletives. False positives are accepted; false
negatives are handled by admin override. Do NOT add partial
common-word fragments (e.g. 'ass' is in 'class') — be conservative.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Blocklist — 35 terms, lowercase only, obvious slurs/expletives only.
# Intentionally avoids fragments that appear in innocent words.
# ---------------------------------------------------------------------------
PROFANITY_TERMS: frozenset[str] = frozenset(
    {
        "nigger",
        "nigga",
        "faggot",
        "fag",
        "kike",
        "chink",
        "spic",
        "wetback",
        "tranny",
        "cunt",
        "twat",
        "clit",
        "bitch",
        "whore",
        "slut",
        "bastard",
        "asshole",
        "arsehole",
        "motherfucker",
        "motherfuck",
        "fuckyou",
        "fuckoff",
        "fuckhead",
        "dickhead",
        "dickwad",
        "shithead",
        "shitstain",
        "wanker",
        "jizz",
        "cumshot",
        "cumslut",
        "pussyhole",
        "cocksucker",
        "cocksuck",
        "ballsack",
    }
)


def is_profane(handle: str) -> bool:
    """Return True if *handle* contains any PROFANITY_TERMS as a substring.

    The check is case-insensitive; *handle* is lowercased before matching.

    Parameters
    ----------
    handle:
        The handle string to inspect (raw, before or after normalisation).

    Returns
    -------
    bool
        ``True`` if any term is found as a substring of the lowercased handle.
    """
    lower = handle.lower()
    return any(term in lower for term in PROFANITY_TERMS)


def find_match(handle: str) -> str | None:
    """Return the first matching term or None — for admin/audit use only.

    Do NOT surface this to end users (avoids dictionary harvesting).
    """
    lower = handle.lower()
    for term in PROFANITY_TERMS:
        if term in lower:
            return term
    return None

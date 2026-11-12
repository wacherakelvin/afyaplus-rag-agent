"""Privacy-masking middleware: detect Kenyan PII, swap it for placeholder tokens before
anything reaches the model, and re-inject the originals only in the final approved answer."""
import re
from collections import Counter
from dataclasses import dataclass, field

# Order matters: emails first (they can contain digits), then structured IDs, then phones.
PATTERNS = [
    ("EMAIL", re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")),
    ("KRA_PIN", re.compile(r"\b[AP]\d{9}[A-Z]\b", re.IGNORECASE)),
    ("MEMBER_ID", re.compile(r"\bAFP-?\d{6}\b", re.IGNORECASE)),
    # Mobile: 07xx / 01xx, or +254 / 254 / (+254) prefix, with optional spaces or dashes between digits
    ("PHONE", re.compile(r"(?<![\d+])(?:\(?\+?254\)?[\s-]?|0)[17](?:[\s-]?\d){8}(?!\d)")),
    # Nairobi landline: 020 xxx xxxx or +254 20 xxx xxxx
    ("PHONE", re.compile(r"(?<![\d+])(?:\(?\+?254\)?[\s-]?|0)20(?:[\s-]?\d){7}(?!\d)")),
]
# National ID numbers are plain 7-8 digit numbers, so they are only masked next to an "ID" keyword
# (masking every 8-digit number would destroy invoice amounts and dates).
NATIONAL_ID = re.compile(r"(?i)(\b(?:national\s+id|id\s*(?:no\.?|number)|id)\s*(?:[:#]|no\.?)?\s*)(\d{7,8})\b")
TOKEN = re.compile(r"\[(?:EMAIL|KRA_PIN|MEMBER_ID|PHONE|NATIONAL_ID)_\d+\]")


def _normalise(kind: str, value: str) -> str:
    """Canonical form, so '0712 345 678' and '+254712345678' share one token."""
    if kind == "PHONE":
        digits = re.sub(r"\D", "", value)
        return "254" + digits[1:] if digits.startswith("0") else digits
    return value.lower()


def detect_pii(text: str) -> dict:
    """Count PII matches without changing the text (used as a defence-in-depth check)."""
    found = Counter()
    for kind, pattern in PATTERNS:
        found[kind] += len(pattern.findall(text))
    found["NATIONAL_ID"] += len(NATIONAL_ID.findall(text))
    return {k: v for k, v in found.items() if v}


@dataclass
class PIIVault:
    """Per-session token vault. Original values never leave this object."""
    _by_token: dict = field(default_factory=dict)
    _by_key: dict = field(default_factory=dict)
    _counts: Counter = field(default_factory=Counter)

    def _token_for(self, kind: str, value: str) -> str:
        key = (kind, _normalise(kind, value))
        if key not in self._by_key:
            self._counts[kind] += 1
            token = f"[{kind}_{self._counts[kind]}]"
            self._by_key[key] = token
            self._by_token[token] = value
        return self._by_key[key]

    def mask(self, text: str) -> tuple[str, dict]:
        """Replace every PII match with a stable placeholder. Returns (masked_text, counts)."""
        found = Counter()

        def replacer(kind):
            def _sub(match):
                found[kind] += 1
                return self._token_for(kind, match.group(0))
            return _sub

        for kind, pattern in PATTERNS:
            text = pattern.sub(replacer(kind), text)

        def _id_sub(match):
            found["NATIONAL_ID"] += 1
            return match.group(1) + self._token_for("NATIONAL_ID", match.group(2))

        text = NATIONAL_ID.sub(_id_sub, text)
        return text, dict(found)

    def demask(self, text: str) -> str:
        """Re-inject original values. Unknown tokens are left untouched."""
        return TOKEN.sub(lambda m: self._by_token.get(m.group(0), m.group(0)), text)
"""Deterministic normalisers and lexicons (implementation spec §6.3).

These are versioned data, owned by the Memory team. Every entry here is a
prototype sample, not a production lexicon.
"""
import re
import unicodedata
from typing import Optional, Tuple

LEXICON_VERSION = "lex-proto-1"

_ws = re.compile(r"\s+")
_ZW = "‌‍"          # ZWNJ/ZWJ appear inside Telugu and Devanagari words


def fold(s: str) -> str:
    """NFC + casefold + whitespace collapse. No transliteration (spec §6.1 step 4)."""
    s = unicodedata.normalize("NFC", s or "")
    s = "".join(ch for ch in s if ch not in _ZW)
    return _ws.sub(" ", s.casefold()).strip()


_tok = re.compile(r"[^\W_]+", re.UNICODE)


def _is_mark(ch: str) -> bool:
    return unicodedata.category(ch).startswith("M")


def tokens(s: str):
    """Split on non-word characters, keeping combining marks attached.

    A plain ``\\w`` regex splits Devanagari and Telugu words at their vowel
    signs. That is exactly the multilingual silent failure the spec warns
    about.
    """
    out, cur = [], []
    for ch in fold(s):
        if ch.isalnum() or _is_mark(ch):
            cur.append(ch)
        else:
            if cur:
                out.append("".join(cur))
                cur = []
    if cur:
        out.append("".join(cur))
    return out


def script_of(s: str) -> str:
    """The dominant script: latin | devanagari | telugu | other."""
    counts = {"latin": 0, "devanagari": 0, "telugu": 0, "other": 0}
    for ch in s:
        if not ch.isalpha():
            continue
        o = ord(ch)
        if o < 0x250:
            counts["latin"] += 1
        elif 0x900 <= o <= 0x97F:
            counts["devanagari"] += 1
        elif 0xC00 <= o <= 0xC7F:
            counts["telugu"] += 1
        else:
            counts["other"] += 1
    return max(counts, key=counts.get) if any(counts.values()) else "other"


# Gazetteer: canonical value -> surface forms, across scripts.
GAZETTEER = {
    "Gurugram": ["gurugram", "gurgaon", "गुरुग्राम", "गुड़गांव", "గురుగ్రామ్"],
    "Delhi": ["delhi", "dilli", "दिल्ली", "ఢిల్లీ"],
    "Pune": ["pune", "पुणे", "పూణే", "పుణె"],
    "Mumbai": ["mumbai", "bombay", "मुंबई", "ముంబై"],
    "Bengaluru": ["bengaluru", "bangalore", "बेंगलुरु", "బెంగళూరు"],
    "Noida": ["noida", "नोएडा"],
}


def gazetteer_lookup(quote: str) -> Optional[str]:
    """The canonical place named in the quote, if the gazetteer knows the form."""
    f = fold(quote)
    for canon, forms in GAZETTEER.items():
        for form in forms:
            if fold(form) in f:
                return canon
    return None


def phone_e164(quote: str) -> Optional[str]:
    digits = re.sub(r"\D", "", quote)
    if len(digits) == 10:
        return "+91" + digits
    if len(digits) == 12 and digits.startswith("91"):
        return "+" + digits
    return None


def resolve_time_expression(expr: Optional[str], observed_at: float) -> Tuple[Optional[float], Optional[float], str]:
    """Resolve a time expression to (valid_from, valid_until, precision).

    This is deliberately small. Unknown expressions resolve to (None, None, "unknown").
    """
    if not expr:
        return None, None, "unknown"
    e = fold(expr)
    if e in ("present", "now", "currently", "abhi", "ippudu"):
        return observed_at, None, "day"            # R-PRESENT (spec §9.5; flagged)
    if e in ("last month",):
        return observed_at - 30, None, "month"
    if e in ("next month", "agle mahine", "अगले महीने", "వచ్చే నెల"):
        return observed_at + 30, None, "month"
    if e in ("next week", "agle hafte", "अगले हफ्ते", "వచ్చే వారం"):
        return observed_at + 7, None, "week"
    if e in ("tomorrow", "kal", "कल", "రేపు"):
        return observed_at + 1, None, "day"
    m = re.fullmatch(r"(\d+) days ago", e)
    if m:
        return observed_at - int(m.group(1)), None, "day"
    m = re.fullmatch(r"in (\d+) days", e)
    if m:
        return observed_at + int(m.group(1)), None, "day"
    m = re.fullmatch(r"until (\d+(?:\.\d+)?)", e)
    if m:
        return None, float(m.group(1)), "day"
    m = re.fullmatch(r"from (\d+(?:\.\d+)?) until (\d+(?:\.\d+)?)", e)
    if m:
        return float(m.group(1)), float(m.group(2)), "day"
    m = re.fullmatch(r"day (\d+(?:\.\d+)?)", e)
    if m:
        return float(m.group(1)), None, "day"
    return None, None, "unknown"


NORMALISERS = {
    "phone_e164": phone_e164,
    "gazetteer_city": gazetteer_lookup,
}

# Assent lexicon, by locale. A reply is assent only when it starts with one of these entries.
AFFIRM = {
    "en": ["yes", "yeah", "yep", "sure", "please do", "go ahead", "yes please"],
    "hi": ["haan", "han", "haanji", "haan ji", "ji haan", "ji", "हाँ", "हां", "जी", "जी हाँ"],
    "te": ["avunu", "sare", "sari", "అవును", "సరే", "హా"],
}
# Acknowledgements are never assent (§5.5 #12).
ACK_BLOCKLIST = ["ok", "okay", "ok thanks", "okay thanks", "thanks", "thank you", "hmm", "acha", "accha",
                 "achha", "noted", "k", "theek", "thik"]
# Tokens in open-namespace leaves or values that trigger a security anomaly (§5.5 #11).
SECURITY_LEXICON = ["admin", "administrator", "superuser", "root", "role", "permission", "access",
                    "discount", "refund", "entitlement", "vip", "premium", "credit", "password",
                    "api_key", "apikey", "owner", "एडमिन", "डिस्काउंट"]
PLACEHOLDER = re.compile(r"^\s*\[(image|audio|video|document|sticker|location|voice note)\]\s*$", re.I)

INTERROGATIVE = re.compile(r"(\?\s*$)|^(shall|should|can|could|would|do you|did you|may i|kya|क्या)\b", re.I)


def is_assent(user_quote: str, max_tokens: int = 6) -> Tuple[bool, str]:
    f = fold(user_quote)
    toks = tokens(f)
    if not toks or len(toks) > max_tokens:
        return False, "length"
    if f in [fold(a) for a in ACK_BLOCKLIST] or " ".join(toks) in [fold(a) for a in ACK_BLOCKLIST]:
        return False, "acknowledgement"
    for words in AFFIRM.values():
        for a in words:
            af = fold(a)
            if f == af or f.startswith(af + " ") or f.startswith(af + ","):
                return True, "assent"
    return False, "not_assent"


def is_interrogative(agent_text: str) -> bool:
    return bool(INTERROGATIVE.search(fold(agent_text)))


def security_hit(*parts: str) -> bool:
    for p in parts:
        f = fold(p).replace(".", " ").replace("_", " ")
        for w in SECURITY_LEXICON:
            if re.search(r"(^|\W)" + re.escape(fold(w)) + r"($|\W)", f):
                return True
    return False


# Future / intent markers (red-team M-7 / R-15). A current-state assertion whose quote carries one of
# these needs a future valid_from, or it is rejected. Prototype sample; recall is [UNMEASURED].
FUTURE_MARKERS = {
    "en": ["will", "going to", "gonna", "next week", "next month", "next year", "planning", "plan to", "soon",
           "tomorrow", "thinking of", "about to", "intend to"],
    "hi": ["agle", "अगले", "jaunga", "jaungi", "jaenge", "जाऊंगा", "जाऊँगा", "जाएंगे", "karunga", "करूंगा",
           "wala hoon", "वाला हूं", "shift hone", "kal"],
    "te": ["వచ్చే", "వెళ్తాను", "వెళ్తా", "రేపు", "అనుకుంటున్నా"],
}


def future_marker(quote: str) -> bool:
    f = " " + " ".join(tokens(quote)) + " "
    for words in FUTURE_MARKERS.values():
        for w in words:
            if " " + " ".join(tokens(w)) + " " in f:
                return True
    return False


# Rendering sanitiser (red-team M-4 / R-12): memory values are data; strip anything that could close the
# memory block or impersonate a role, and cap the length.
_ROLE = re.compile(r"(^|\s)(system|assistant|user|developer|tool)\s*:", re.I)
_DELIM = re.compile(r"<<|>>|</?\w*memory\w*>|```", re.I)
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def sanitise_value(v: str, cap: int = 80) -> str:
    v = _CTRL.sub(" ", v or "")
    v = _DELIM.sub(" ", v)
    v = _ROLE.sub(" ", v)
    v = _ws.sub(" ", v).strip()
    return v[:cap]


def search_tokens(s: str):
    """Search tokens through the gate's normaliser (red-team M-11): fold + gazetteer canonical forms."""
    out = set(tokens(s))
    for t in list(out):
        c = gazetteer_lookup(t)
        if c:
            out.add(fold(c))
    c = gazetteer_lookup(s)
    if c:
        out.add(fold(c))
    return out

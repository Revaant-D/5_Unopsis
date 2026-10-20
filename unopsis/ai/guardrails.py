"""
Guardrails around every model call: what goes in, and what is allowed back out.

Three jobs, in the order a message meets them:

1. PREPROCESSING (clean_message_text). Messages arrive from email, Slack and chat apps, so
   they carry HTML, invisible control characters, runs of whitespace and personal data. The
   text is normalised, stripped of markup, has e-mail addresses / phone numbers / links
   replaced by placeholders (they are never useful for triage and should not leave the
   machine for an external API), and is cut to MAX_INPUT_CHARS.

2. INPUT SCREENING (find_injection). A message is DATA written by somebody else, never an
   instruction to us. Text that tries to talk to the model ("ignore previous instructions",
   chat-template tokens, "you are now...") is flagged. Flagged text typed into the AI lab is
   refused; a flagged message inside a brief is held back for a human to read and is never
   forwarded to either model.

3. OUTPUT VALIDATION (parse_json_object, validate_triage, validate_brief). Small models
   break their output format often: prose around the JSON, code fences, a lane that does not
   exist, a 300-word "summary". Output is parsed leniently, then validated strictly against
   the allowed values; anything that does not validate is replaced by the rule-based result
   (rule_based_triage), so a broken model answer can never reach the page or the database.
"""

import json
import re
import unicodedata

# The lanes a message can be triaged into. The first three are BriefItem.Lane values;
# "noise" is the Message.is_noise flag (promotions, automated mail).
LANES = ("needs_you", "moving", "fyi", "noise")

MAX_INPUT_CHARS = 2000
MAX_SUMMARY_CHARS = 200
MAX_DEADLINE_CHARS = 60
MAX_HEADLINE_CHARS = 120
MAX_BRIEF_BODY_CHARS = 1500

# ---------------------------------------------------------------------------- preprocessing

_TAG_RE = re.compile(r"<[^>]{0,500}>")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!\w)\+?\(?\d[\d\s().-]{7,}\d(?!\w)")


def _redact_phone(match):
    # Ten or more digits is a phone number; fewer is a date, an amount or an invoice number,
    # which triage needs to keep ("due 2026-10-19", "Invoice #4471").
    return "[phone]" if len(re.sub(r"\D", "", match.group(0))) >= 10 else match.group(0)
_SPACE_RE = re.compile(r"\s+")


def clean_message_text(text, max_chars=MAX_INPUT_CHARS):
    """
    Normalise one raw message body for a model.

    >>> clean_message_text("<p>Mail me at a.b@x.edu</p>\\n\\n  thanks")
    'Mail me at [email] thanks'
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    # Drop control and format characters (zero-width spaces, bidi overrides) but keep
    # ordinary whitespace, which the next steps collapse.
    text = "".join(
        ch for ch in text
        if ch in "\n\t " or unicodedata.category(ch)[0] != "C"
    )
    text = _TAG_RE.sub(" ", text)
    text = _URL_RE.sub("[link]", text)
    text = _EMAIL_RE.sub("[email]", text)
    text = _PHONE_RE.sub(_redact_phone, text)
    text = _SPACE_RE.sub(" ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + " ..."
    return text


# ------------------------------------------------------------------------- input screening

_INJECTION_PATTERNS = [
    (r"\b(ignore|disregard|forget)\b.{0,40}\b(instructions?|prompts?|rules|above|previous)\b",
     "asks the model to ignore its instructions"),
    (r"\b(system|developer)\s+(prompt|message|mode)\b", "mentions the system prompt"),
    (r"\byou are (now|no longer)\b", "tries to give the model a new role"),
    (r"\b(act|pretend|roleplay) as\b", "tries to give the model a new role"),
    (r"\bjailbreak|\bdo anything now\b", "known jailbreak wording"),
    (r"<\|?(im_start|im_end|system|assistant|user|endoftext|eot_id)\|?>", "chat-template token"),
    (r"\[/?INST\]|<<SYS>>|###\s*(instruction|system)", "chat-template token"),
    (r"\b(reveal|print|show|repeat)\b.{0,30}\b(prompt|instructions|api key|secret)\b",
     "asks for hidden instructions or secrets"),
]
_INJECTION_RES = [(re.compile(p, re.IGNORECASE | re.DOTALL), why) for p, why in _INJECTION_PATTERNS]


def find_injection(text):
    """The reasons `text` looks like a prompt-injection attempt; an empty list if it does not."""
    reasons = []
    for pattern, why in _INJECTION_RES:
        if pattern.search(text or "") and why not in reasons:
            reasons.append(why)
    return reasons


# ------------------------------------------------------------------------ output validation

_FENCE_RE = re.compile(r"```(?:json)?", re.IGNORECASE)


def parse_json_object(text):
    """
    The first JSON object found in a model's reply, or None.

    Lenient on purpose: small models wrap JSON in code fences or a sentence of preamble, and
    a scan for the first balanced {...} recovers most of those. Strictness comes afterwards,
    in the validate_* functions.
    """
    if not text:
        return None
    text = _FENCE_RE.sub("", str(text))
    start = text.find("{")
    while start != -1:
        depth, in_string, escaped = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(text[start:i + 1])
                    except ValueError:
                        break
                    return value if isinstance(value, dict) else None
        start = text.find("{", start + 1)
    return None


def _short(value, limit):
    if not isinstance(value, str):
        return ""
    value = _SPACE_RE.sub(" ", value).strip()
    if len(value) > limit:
        value = value[:limit].rsplit(" ", 1)[0] + "..."
    return value


def validate_triage(obj):
    """
    A clean {"lane", "summary", "deadline"} dict, or None when `obj` is not a usable answer.

    The lane must be one of LANES exactly (case and spaces forgiven, "needs you" accepted).
    The summary must be non-empty. The deadline is optional and kept short.
    """
    if not isinstance(obj, dict):
        return None
    lane = str(obj.get("lane", "")).strip().lower().replace(" ", "_").replace("-", "_")
    if lane not in LANES:
        return None
    summary = _short(obj.get("summary"), MAX_SUMMARY_CHARS)
    if not summary:
        return None
    deadline = obj.get("deadline")
    deadline = _short(deadline, MAX_DEADLINE_CHARS) if isinstance(deadline, str) else ""
    if deadline.lower() in {"", "none", "null", "n/a", "no deadline"}:
        deadline = ""
    return {"lane": lane, "summary": summary, "deadline": deadline or None}


def validate_brief(obj):
    """A clean {"headline", "body"} dict, or None."""
    if not isinstance(obj, dict):
        return None
    headline = _short(obj.get("headline"), MAX_HEADLINE_CHARS)
    body = obj.get("body")
    if isinstance(body, list):
        body = " ".join(str(part) for part in body)
    body = _short(body, MAX_BRIEF_BODY_CHARS)
    if not headline or not body:
        return None
    return {"headline": headline, "body": body}


# ------------------------------------------------------------------------- rule fallback

_NOISE_WORDS = re.compile(
    r"\b(sale|% off|\d+% off|discount|promo|unsubscribe|newsletter|left something in your cart|"
    r"limited time|deal)\b", re.IGNORECASE)
_NEEDS_YOU_WORDS = re.compile(
    r"\b(please|can you|could you|approve|approval|need you|needs your|deadline|due|overdue|"
    r"by (mon|tues|wednes|thurs|fri|satur|sun)day|before|asap|urgent|resend|reply|confirm|"
    r"make it)\b|\?\s*$", re.IGNORECASE)
_MOVING_WORDS = re.compile(
    r"\b(i can take|i'll|i will|looking into|on it|rolling back|fixed|deployed|working on|"
    r"handled|confirmed)\b", re.IGNORECASE)
_DEADLINE_RE = re.compile(
    r"\b(by|before|due|on)\s+((?:mon|tues|wednes|thurs|fri|satur|sun)day|tomorrow|tonight|"
    r"the \d{1,2}(?:st|nd|rd|th)?|\w+ \d{1,2})\b|\b(friday|sunday at \d+)\b", re.IGNORECASE)


def rule_based_triage(text):
    """
    The deterministic fallback: keyword rules, no model.

    Used when the local model is not installed, fails, or returns something validate_triage
    rejects -- so the feature degrades to "less clever" rather than to an error page.
    """
    text = text or ""
    if _NOISE_WORDS.search(text):
        lane = "noise"
    elif _NEEDS_YOU_WORDS.search(text):
        lane = "needs_you"
    elif _MOVING_WORDS.search(text):
        lane = "moving"
    else:
        lane = "fyi"
    match = _DEADLINE_RE.search(text)
    words = text.split()
    summary = " ".join(words[:18]) + (" ..." if len(words) > 18 else "")
    return {"lane": lane, "summary": summary or "(empty message)",
            "deadline": match.group(0) if match else None}

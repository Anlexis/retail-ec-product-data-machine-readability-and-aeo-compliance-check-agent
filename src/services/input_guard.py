"""AgentCore Platform v1.0 — RET-C2-196 caller-input contract"""

# Every bound this agent places on caller data lives here, so the HTTP adapter and
# the node that owns the caller contract enforce one set of rules rather than two
# that drift. The node is the authority: the adapter is out of the path when the
# platform gateway calls the agent directly, so anything the adapter refuses the
# node must refuse too.
#
# Three shapes of caller data arrive:
#   - free text on `user_input`, parsed as a product listing;
#   - structured records on the request context channel (`products`);
#   - scalar request metadata on the same channel (`channel`, `merchant_id`).
#
# Rules that apply to all three:
#   - a refusal names the FIELD and a closed-set reason, never the value;
#   - an unsupported key is DROPPED, not ignored — see `validate_context`;
#   - every caller string that can reach the report is locked to an inert
#     identifier alphabet, because the report is Markdown and free text there is
#     caller-controlled output;
#   - every caller number goes through a finite + bounded parser.

from __future__ import annotations

import re
import unicodedata
from typing import Any

from framework.security.credential_detector import detect_credentials_in_value

# The platform's input filter replaces personal-data shapes with this sentinel
# before any template code runs. It is an ordinary string by the time we see it,
# which is why it has to be recognised explicitly rather than scored as content.
MASK_SENTINEL = "[MASKED]"

# ── Structural bounds ────────────────────────────────────────────────────────
MAX_INPUT_LENGTH = 50_000
MAX_PRODUCTS = 200
MAX_TEXT_FIELD = 4_000
MAX_ATTRIBUTES = 50
MAX_ATTR_VALUE = 256
MAX_IDENTIFIER = 64
MAX_URL = 2_048

# Rendered caller strings are locked to this alphabet. Retail identifiers use
# digits, letters, dot, dash and underscore — a barcode, an internal SKU and a
# variant suffix all fit. Nothing in it can open a Markdown construct, so a
# caller cannot manufacture a heading, a table row or a list item in the report.
_INERT_IDENTIFIER = re.compile(r"\A[A-Za-z0-9._-]{1,64}\Z")
# Request metadata is narrower still and case-normalised.
_INERT_SLUG = re.compile(r"\A[a-z0-9_-]{1,32}\Z")

_SAFE_URL = re.compile(r"\Ahttps?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{1,2040}\Z")

# ── Injection screening ──────────────────────────────────────────────────────
#
# Two separate classes, because they fail differently.
#
# 1. Chat-template CONTROL TOKENS. These are structural — they end one speaker's
#    turn and open another's — so they are screened as a class rather than as a
#    list of phrases. The framework scores `<|im_start|>` and `[INST]` but returns
#    nothing for `<<SYS>>`, which is exactly what would hide it.
_CONTROL_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<\|[^|>]{0,64}\|>"),  # <|im_start|>, <|endoftext|>, …
    re.compile(r"\[/?INST\]", re.IGNORECASE),  # [INST] … [/INST]
    re.compile(r"<</?SYS>>", re.IGNORECASE),  # <<SYS>> … <</SYS>>
    re.compile(r"</?s>", re.IGNORECASE),  # <s> … </s>
    re.compile(r"</?system>", re.IGNORECASE),  # <system> … </system>
)

# 2. Directive phrases. Every phrase here names an instruction addressed to the
#    model. Phrases that also occur in ordinary retail copy are deliberately
#    ABSENT: "you are now" matches "You are now ready to brew…" and
#    "forget everything" matches "Forget everything you knew about…". Both were
#    measured against real listing copy and both refused a legitimate request.
#    The anchored "…previous instructions" forms below cover the attack they were
#    meant to cover, without the false positive.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(ignore|disregard|forget)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all)\b"
        r"[^.\n]{0,20}\b(instruction|instructions|prompt|prompts|rule|rules|context)\b",
        r"\b(reveal|print|output|repeat|show)\b[^.\n]{0,30}\b(your|the)\b[^.\n]{0,20}"
        r"\b(system prompt|system message|instructions|initial prompt)\b",
        r"\b(override|bypass|disable)\b[^.\n]{0,30}\b(your|the|all)\b[^.\n]{0,20}"
        r"\b(instruction|instructions|rule|rules|guardrail|guardrails|safety)\b",
        r"\byou\s+are\s+now\s+(a|an|the)\b",
        r"\bact\s+as\s+(a|an|the)\s+(unrestricted|unfiltered|jailbroken|developer)\b",
    )
)

# Markup is stripped before the screens run a second time. A directive split by
# tags ("ig<b>nore</b> previous instructions") reassembles into a plain match,
# and the strip is why the token screen runs on the RAW text first: stripping
# `<s>` would remove the very token we are looking for.
_MARKUP = re.compile(r"<[^>]{0,64}>")

# ── PII screening ────────────────────────────────────────────────────────────
#
# The narrow shapes matter more here than in most templates: the whole input is a
# product listing, and product listings are FULL of long digit runs. An
# unanchored 13-16 digit "card" pattern and a bare-digit-run "phone" pattern
# between them refused every EAN-13, GTIN-14, UPC-A, model number and dimension
# list put through them — which is to say, the normal case.
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# `\b` is computed over `\w`, which includes Kana and Kanji — so there is no word
# boundary between 話 and 0, and `電話03-1234-5678` matches nothing while the
# space-separated ASCII form matches. Japanese is written without spaces, so the
# case that fails is the ordinary one for this template's market. These
# lookarounds test for an identifier character explicitly instead.
_NOT_IDENT_BEFORE = r"(?<![0-9A-Za-z_-])"
_NOT_IDENT_AFTER = r"(?![0-9A-Za-z_-])"

# Separator-bearing phone shapes only. A run of digits with no separator is a
# barcode far more often than a telephone number in this domain.
_PHONE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\+\d{1,3}[\s.-]\d{1,4}[\s.-]\d{3,4}[\s.-]\d{3,4}" + _NOT_IDENT_AFTER),
    re.compile(r"\(\d{2,4}\)\s?\d{3,4}[\s.-]\d{4}" + _NOT_IDENT_AFTER),
    re.compile(_NOT_IDENT_BEFORE + r"0\d{1,4}-\d{1,4}-\d{4}" + _NOT_IDENT_AFTER),
    re.compile(_NOT_IDENT_BEFORE + r"\d{3}-\d{3}-\d{4}" + _NOT_IDENT_AFTER),
)

# The Japanese individual number, which the framework's own detector also misses
# when written without surrounding spaces. Gated on its context marker rather
# than matched on shape alone: a dashed 4-4-4 digit group is equally a retail
# model number, and `Model 1234-5678-9012` is ordinary listing text. Requiring
# the marker catches the real case without refusing the catalogue.
_MY_NUMBER_JP = re.compile(
    r"(?:個人番号|マイナンバー|my\s?number)\D{0,8}"
    + _NOT_IDENT_BEFORE
    + r"(?:\d{4}[\s-]?\d{4}[\s-]?\d{4})"
    + _NOT_IDENT_AFTER,
    re.IGNORECASE,
)

# Conventionally grouped card numbers, plus unseparated runs that pass BOTH a
# Luhn check and a major issuer prefix. Lengths are restricted to 15, 16 and 19:
# the GS1 identifier lengths a retail feed actually carries — 12 (UPC-A),
# 13 (EAN-13/JAN), 14 (GTIN-14/ITF-14) and 18 (SSCC) — are therefore out of
# reach of this pattern by construction rather than by luck.
_CARD_GROUPED = (
    re.compile(_NOT_IDENT_BEFORE + r"\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{4}" + _NOT_IDENT_AFTER),
    re.compile(_NOT_IDENT_BEFORE + r"\d{4}[ -]\d{6}[ -]\d{5}" + _NOT_IDENT_AFTER),
)
_CARD_RUN = re.compile(_NOT_IDENT_BEFORE + r"(?:\d{15}|\d{16}|\d{19})" + _NOT_IDENT_AFTER)
_CARD_IIN = re.compile(
    r"\A(?:4"  # Visa
    r"|5[1-5]"  # Mastercard
    r"|2(?:2[2-9]|[3-6]\d|7[01]|720)"  # Mastercard 2-series
    r"|3[47]"  # American Express
    r"|6011|65"  # Discover
    r"|35)"  # JCB
)


def _luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for index, char in enumerate(digits):
        value = ord(char) - 48
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _looks_like_card(text: str) -> bool:
    if any(p.search(text) for p in _CARD_GROUPED):
        return True
    return any(_CARD_IIN.match(m.group()) and _luhn_ok(m.group()) for m in _CARD_RUN.finditer(text))


def scan_pii(text: str) -> str:
    """Return a closed-set PII kind found in ``text``, else ``""``."""
    if _EMAIL.search(text):
        return "email"
    if _MY_NUMBER_JP.search(text):
        return "national_id"
    if any(p.search(text) for p in _PHONE_PATTERNS):
        return "phone"
    if _looks_like_card(text):
        return "payment_card"
    return ""


def scan_injection(text: str) -> str:
    """Return a closed-set injection kind found in ``text``, else ``""``.

    Screened three ways, because each catches what the others cannot:
      - raw, which is the only place a control token survives intact;
      - Unicode-normalised, so a compatibility-form lookalike cannot slip past;
      - markup-stripped, which reassembles a directive split by tags.
    """
    stripped = _MARKUP.sub("", text)
    normalised = unicodedata.normalize("NFKC", text)
    for candidate in (text, normalised):
        if any(p.search(candidate) for p in _CONTROL_TOKEN_PATTERNS):
            return "control_token"
    for candidate in (text, normalised, stripped):
        if any(p.search(candidate) for p in _INJECTION_PATTERNS):
            return "directive"
    return ""


def screen_text(text: str) -> str:
    """Return a closed-set refusal reason for a caller text value, else ``""``."""
    hit = scan_injection(text)
    if hit:
        return hit
    # Credentials are screened before PII so the closed-set reason is accurate:
    # a database URI carries an `@` and would otherwise be reported as an email.
    # Both are refused either way; the label is what the caller acts on.
    if detect_credentials_in_value(text):
        return "credential"
    hit = scan_pii(text)
    if hit:
        return f"pii_{hit}"
    return ""


def scan_structure(value: Any, _depth: int = 0) -> str:
    """Depth-first screen over a parsed payload, KEYS included.

    A JSON payload can carry a control token in a key name, or hide one behind a
    ``\\u`` escape that only exists once the document is parsed. Screening the raw
    request text alone sees neither.
    """
    if _depth > 8:
        return "nesting_depth"
    if isinstance(value, str):
        return screen_text(value)
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                hit = screen_text(key)
                if hit:
                    return hit
            hit = scan_structure(item, _depth + 1)
            if hit:
                return hit
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            hit = scan_structure(item, _depth + 1)
            if hit:
                return hit
    return ""


# ── Numeric parsing ──────────────────────────────────────────────────────────


def finite_in_range(value: Any, low: float, high: float) -> float | None:
    """Parse a caller number, or ``None`` if it is not a finite value in range.

    ``float("NaN")`` parses without complaint and every comparison against it is
    False, so an unchecked non-finite value does not raise — it quietly answers
    "no" to whatever question the agent exists to ask. ``bool`` is rejected
    because it is a subclass of ``int``.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except (ValueError, AttributeError):
            return None
    elif isinstance(value, (int, float)):
        number = float(value)
    else:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    if not low <= number <= high:
        return None
    return number


# ── Rendered-value locks ─────────────────────────────────────────────────────


def is_inert_identifier(value: str) -> bool:
    """True when ``value`` is safe to render verbatim into the Markdown report."""
    return bool(_INERT_IDENTIFIER.match(value))


def coerce_identifier(value: Any, fallback: str) -> str:
    """Return ``value`` if it is an inert identifier, else ``fallback``.

    Used on the one caller string the report renders. A SKU id that is not inert
    is replaced rather than escaped: escaping preserves attacker-chosen text in
    the output, and a positional label is enough for the merchant to find the row.
    """
    if isinstance(value, str) and is_inert_identifier(value):
        return value
    return fallback


# ── Request context contract ─────────────────────────────────────────────────

_CONTEXT_KEYS = ("channel", "merchant_id", "products")

_PRODUCT_TEXT_FIELDS = ("title", "description", "category", "brand")


def _refuse(field: str, reason: str) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    return {}, [(reason, field)]


def validate_product(record: Any) -> tuple[dict[str, Any], str]:
    """Validate one caller product record. Returns ``(record, "")`` or ``({}, reason)``."""
    if not isinstance(record, dict):
        return {}, "not_an_object"

    sku_id = record.get("sku_id", record.get("id", ""))
    if not isinstance(sku_id, str) or not is_inert_identifier(sku_id):
        return {}, "sku_id_not_an_identifier"

    clean: dict[str, Any] = {"sku_id": sku_id}

    for field in _PRODUCT_TEXT_FIELDS:
        value = record.get(field, "")
        if value in (None, ""):
            clean[field] = ""
            continue
        if not isinstance(value, str):
            return {}, f"{field}_not_a_string"
        if len(value) > MAX_TEXT_FIELD:
            return {}, f"{field}_too_long"
        clean[field] = value

    price = record.get("price", "")
    if price in (None, ""):
        clean["price"] = ""
    else:
        parsed = finite_in_range(price, 0.0, 1e12)
        if parsed is None:
            return {}, "price_not_a_finite_amount"
        clean["price"] = parsed

    attributes = record.get("attributes", {})
    if attributes in (None, ""):
        attributes = {}
    if not isinstance(attributes, dict):
        return {}, "attributes_not_an_object"
    if len(attributes) > MAX_ATTRIBUTES:
        return {}, "attributes_too_many"
    clean_attrs: dict[str, str] = {}
    for key, value in attributes.items():
        if not isinstance(key, str) or not _INERT_SLUG.match(key.lower()):
            return {}, "attribute_name_not_an_identifier"
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            return {}, "attribute_value_not_a_scalar"
        text = str(value)
        if len(text) > MAX_ATTR_VALUE:
            return {}, "attribute_value_too_long"
        clean_attrs[key.lower()] = text
    clean["attributes"] = clean_attrs

    image_url = record.get("image_url", record.get("image", ""))
    if image_url in (None, ""):
        clean["image_url"] = ""
    elif not isinstance(image_url, str) or len(image_url) > MAX_URL or not _SAFE_URL.match(image_url):
        return {}, "image_url_not_a_url"
    else:
        clean["image_url"] = image_url

    hit = scan_structure(clean)
    if hit:
        return {}, hit
    return clean, ""


def validate_context(raw: Any) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Reduce a caller request context to the supported, screened subset.

    Returns ``(accepted, refusals)`` where each refusal is ``(reason, field)``.

    Unsupported keys are DROPPED rather than ignored, and the difference is not
    cosmetic. An ignored key still travels on the context channel; the
    framework's first node returns that channel verbatim inside its own result;
    the framework's output scan then sees it. A credential-shaped value on a key
    this agent never declared therefore fails the whole run at the first node,
    before any template code runs, with an error the caller cannot act on. The
    only way to be immune is to not carry the key at all.
    """
    if raw is None:
        return {}, []
    if not isinstance(raw, dict):
        return _refuse("input_context", "not_an_object")

    accepted: dict[str, Any] = {}

    for field in ("channel", "merchant_id"):
        if field not in raw:
            continue
        value = raw[field]
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            return _refuse(field, "not_an_identifier")
        # Screen the value the CALLER SENT, before any normalisation. Case-folding
        # first would hand the detector a string the caller never wrote: an AWS
        # key id is an uppercase shape, so `AKIA…` lowercased stops matching and
        # is accepted. Normalising afterwards keeps the refusal set a property of
        # the request rather than of our own transform.
        if detect_credentials_in_value(value):
            return _refuse(field, "credential_shape")
        normalised = value.strip().lower()
        if not _INERT_SLUG.match(normalised):
            return _refuse(field, "not_an_identifier")
        accepted[field] = normalised

    if "products" in raw and raw["products"] not in (None, ""):
        products = raw["products"]
        if not isinstance(products, list):
            return _refuse("products", "not_a_list")
        if len(products) > MAX_PRODUCTS:
            return _refuse("products", "too_many_records")
        clean_products: list[dict[str, Any]] = []
        for index, record in enumerate(products):
            clean, reason = validate_product(record)
            if reason:
                return _refuse(f"products[{index}]", reason)
            clean_products.append(clean)
        accepted["products"] = clean_products

    # The framework's own detector over what the caller actually sent, field by
    # field. Per-field scanning is exactly equivalent to scanning the whole
    # mapping — `detect_credentials_in_value` on a dict is defined as the union
    # over its values — which is what lets the refusal name a field without
    # widening or narrowing what is blocked. Scalars were screened above, before
    # normalisation; `products` is screened here in the shape it arrived.
    for field in _CONTEXT_KEYS:
        if field in raw and detect_credentials_in_value(raw[field]):
            return _refuse(field, "credential_shape")

    # Keys outside _CONTEXT_KEYS were never copied into `accepted` above, so they
    # are already gone. Dropping rather than refusing is deliberate: an
    # unsupported key is usually a client that knows more than this version does,
    # and nothing it carries can reach the graph once it is not copied.
    return accepted, []

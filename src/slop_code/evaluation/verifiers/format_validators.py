import ipaddress
import re
import uuid
from collections.abc import Callable
from collections.abc import Iterable
from datetime import datetime

from pydantic import JsonValue

# ---------------------------
# Validator Registry (core)
# ---------------------------


class ValidatorRegistry:
    _REGISTRY: dict[str, Callable[[str], bool]] = {}
    _CANONICAL: dict[str, str] = {}

    @classmethod
    def register(cls, name: str, aliases: Iterable[str] = ()):
        """Decorator to register a validator under a canonical name + aliases."""
        canonical = name.strip().lower()

        def deco(func: Callable[[str], bool]):
            cls._REGISTRY[canonical] = func
            cls._CANONICAL[canonical] = canonical
            for a in aliases:
                a_norm = a.strip().lower()
                cls._REGISTRY[a_norm] = func
                cls._CANONICAL[a_norm] = canonical
            return func

        return deco

    @classmethod
    def validate(cls, s: str, fmt: str) -> str:
        key = (fmt or "").strip().lower()
        func = cls._REGISTRY.get(key)
        if not func:
            raise ValueError(f"Unknown format: {fmt}")
        ok = bool(func(s))
        canonical = cls._CANONICAL[key].upper()
        return f"VALID_{canonical}" if ok else "MALFORMED"


REGISTRY = ValidatorRegistry()


def validate_format(s: JsonValue, fmt: str) -> str:
    """
    Public API: returns 'VALID_{FORMAT}' if s conforms; else 'MALFORMED'.
    Add new formats with @registry.register("name", aliases=[...]).
    """
    if not isinstance(s, str):
        s = str(s)
    return REGISTRY.validate(s, fmt)


# ---------------------------
# Built-in Validators
# ---------------------------


@ValidatorRegistry.register("timestamp", aliases=["iso8601", "unix", "unix_timestamp"])
def _v_timestamp(s: str) -> bool:
    # ISO 8601 (with optional Z) using fromisoformat; falls back to numeric UNIX
    try:
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        return True
    except Exception:
        pass
    # Numeric UNIX (seconds or ms); accept int/float-like
    try:
        float(s)
        return True
    except Exception:
        return False


@ValidatorRegistry.register("date", aliases=["calendar_date"])
def _v_date(s: str) -> bool:
    # Popular date layouts (extend as needed)
    patterns = [
        "%m%d%y",
        "%m%d%Y",
        "%m/%d/%y",
        "%m/%d/%Y",
        "%d/%m/%y",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%d %b %Y",
        "%d %B %Y",  # 01 Jan 2025 / 01 January 2025
    ]
    for p in patterns:
        try:
            datetime.strptime(s, p)
            return True
        except ValueError:
            continue
    return False


@ValidatorRegistry.register("uuid", aliases=["guid"])
def _v_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except Exception:
        return False


@ValidatorRegistry.register("ip", aliases=["ip_address"])
def _v_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except Exception:
        return False


# Separate strict IPv4/IPv6 aliases if you want to check the version specifically
@ValidatorRegistry.register("ipv4")
def _v_ipv4(s: str) -> bool:
    try:
        return ipaddress.ip_address(s).version == 4
    except Exception:
        return False


@ValidatorRegistry.register("ipv6")
def _v_ipv6(s: str) -> bool:
    try:
        return ipaddress.ip_address(s).version == 6
    except Exception:
        return False


@ValidatorRegistry.register("email", aliases=["e-mail"])
def _v_email(s: str) -> bool:
    # Pragmatic email regex (kept simple on purpose)
    return bool(re.fullmatch(r"^[\w\.-]+@[\w\.-]+\.\w+$", s))


@ValidatorRegistry.register("url", aliases=["uri", "link"])
def _v_url(s: str) -> bool:
    # Simple, permissive URL check for http/https/ftp
    return bool(re.fullmatch(r"^(https?|ftp)://[^\s/$.?#].[^\s]*$", s))


@ValidatorRegistry.register("phone", aliases=["telephone"])
def _v_phone(s: str) -> bool:
    # Generic international-ish pattern (very permissive)
    return bool(
        re.fullmatch(
            r"^\+?\d{1,3}?[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,9}([-.\s]?\d{1,9})?$", s
        )
    )


@ValidatorRegistry.register("hex", aliases=["hex_color", "hexcode"])
def _v_hex(s: str) -> bool:
    return bool(re.fullmatch(r"#?([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})", s))


@ValidatorRegistry.register("base64")
def _v_base64(s: str) -> bool:
    # Structural validation only (no decode)
    return bool(
        re.fullmatch(
            r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?", s
        )
    )


@ValidatorRegistry.register("json")
def _v_json(s: str) -> bool:
    import json

    try:
        json.loads(s)
        return True
    except Exception:
        return False


# ---------------------------
# Examples of adding formats
# ---------------------------


# 1) Credit card (Luhn + basic length/bin sanity). Not bulletproof but handy.
def _luhn_ok(digits: str) -> bool:
    total = 0
    rev = digits[::-1]
    for i, ch in enumerate(rev):
        n = ord(ch) - 48  # int(ch) but faster
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


@ValidatorRegistry.register("credit_card", aliases=["cc", "card"])
def _v_credit_card(s: str) -> bool:
    digits = re.sub(r"\D", "", s)
    if not 12 <= len(digits) <= 19:
        return False
    return _luhn_ok(digits)


# 2) US ZIP (5 or ZIP+4)
@ValidatorRegistry.register("us_zip", aliases=["zip"])
def _v_us_zip(s: str) -> bool:
    return bool(re.fullmatch(r"^\d{5}(-\d{4})?$", s))

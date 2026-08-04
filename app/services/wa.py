"""wa.me deep links.

Deliberately the only outbound WhatsApp mechanism in the system. No Business
API dependency, no template approval, and the message leaves from the owner's
own number after they read it.
"""

from urllib.parse import quote


def normalise_phone(phone: str, default_cc: str = "91") -> str:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) == 10:
        return default_cc + digits
    return digits.lstrip("0")


def wa_link(phone: str, message: str) -> str:
    return f"https://wa.me/{normalise_phone(phone)}?text={quote(message)}"

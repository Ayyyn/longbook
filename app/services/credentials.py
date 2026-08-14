"""Getting an owner's access token into their hands, and back again.

The token is stored only as a SHA-256 digest, so it genuinely cannot be
recovered — not from the database, not by us. That is the right call for a
credential, but it means the one screen that shows it is the only chance the
owner gets, and an owner who clears their browser or buys a new phone is
locked out of their own records with no way back.

So two things live here: emailing the token at signup, so it survives in a
place they can search, and re-issuing it when they ring to say it is gone.

Both widen exposure — a token in an inbox is readable by anyone with the
inbox. That is an accepted trade for a launch cohort we onboard by hand, and
it is the wrong answer for a hundred customers. The right answer is
short-lived sessions, which is still deferred.
"""

from __future__ import annotations

import logging

from app.services.mailer import send_email

log = logging.getLogger(__name__)


def _body(business_name: str, phone: str, token: str, dashboard_url: str) -> tuple[str, str]:
    text = f"""Your Longbook sign-in details

Business: {business_name}

Sign in at: {dashboard_url}/login

  Phone number:  {phone}
  Access token:  {token}

Keep this email. The token is not stored anywhere we can read it, so if you
lose it we cannot look it up — we can only issue you a new one, which stops
the old one working.

You do not need to type this in every day. Once you have signed in on your
phone it stays signed in. You need it again only on a new phone, or if you
clear your browser.

If you did not set up this account, please tell us and ignore this email.
"""

    html = f"""<html><body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
color:#1a1917;line-height:1.55;max-width:560px">
<h2 style="margin:0 0 16px;font-weight:600">Your Longbook sign-in details</h2>
<p style="margin:0 0 8px"><strong>{business_name}</strong></p>
<table style="border-collapse:collapse;margin:16px 0;width:100%">
  <tr><td style="padding:8px 0;color:#6f6c66">Phone number</td>
      <td style="padding:8px 0;font-weight:600;text-align:right">{phone}</td></tr>
  <tr><td style="padding:8px 0;color:#6f6c66">Access token</td>
      <td style="padding:8px 0;text-align:right"><code
        style="font-size:15px;word-break:break-all">{token}</code></td></tr>
</table>
<p style="margin:0 0 16px">
  <a href="{dashboard_url}/login"
     style="display:inline-block;background:#0d5c34;color:#fff;text-decoration:none;
            padding:12px 20px;border-radius:10px;font-weight:600">Sign in</a>
</p>
<p style="margin:0 0 12px;color:#45433f"><strong>Keep this email.</strong> The token is not
stored anywhere we can read it, so if you lose it we cannot look it up — we can only issue
a new one, which stops the old one working.</p>
<p style="margin:0 0 12px;color:#45433f">You do not need this every day. Once you have signed
in on your phone it stays signed in. You need it again only on a new phone, or if you clear
your browser.</p>
<p style="margin:0;color:#6f6c66;font-size:14px">If you did not set up this account, please
tell us and ignore this email.</p>
</body></html>"""
    return text, html


def email_token(
    *, to: str | None, business_name: str, phone: str, token: str, dashboard_url: str
) -> tuple[bool, str]:
    """Send the sign-in details. Never raises — signup must not fail on mail.

    A tenant that exists with an email nobody received is recoverable (re-issue
    the token). A signup that 500s because the mail server was down is not.
    """
    if not to:
        return False, "No email address given at signup."
    text, html = _body(business_name, phone, token, dashboard_url.rstrip("/"))
    sent, detail = send_email(to, f"Your Longbook access — {business_name}", text, html)
    if not sent:
        log.warning("Could not email the access token: %s", detail)
    return sent, detail

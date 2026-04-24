"""
Email notifier.

Uses stdlib ``smtplib`` + ``email.message.EmailMessage`` so any SMTP
relay works (SendGrid, Postmark, Mailgun, SES, corporate Postfix).

Rendering is a pair of string templates — HTML + plain-text fallback
— kept inline here because the surface is small and adding Jinja2 is
not worth a new dependency yet. If email content grows, promote the
templates into ``templates/alert.html`` + swap in Jinja2.

Security
--------
* Prompt and summary strings are HTML-escaped before interpolation.
* URLs in the body are built from settings.PUBLIC_BASE_URL + the alert
  id; we never render user-supplied URLs raw.
"""

from __future__ import annotations

import html
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional

from app.config import get_settings
from app.logging_setup import get_logger
from app.models import Alert, ChangeEvent, UserSubscription
from app.services.notifiers.base import NotifierError

log = get_logger(__name__)


# ── Rendering ────────────────────────────────────────────────────────────────

def _score_band(score: Optional[float]) -> str:
    """Human label for the numeric significance score."""
    if score is None:
        return "unscored"
    if score >= 0.80:
        return "CRITICAL"
    if score >= 0.60:
        return "substantive"
    if score >= 0.40:
        return "clarification"
    if score >= 0.20:
        return "minor"
    return "cosmetic"


def _fmt_list(values: Optional[list]) -> str:
    if not values:
        return "—"
    return ", ".join(str(v) for v in values)


def _render_subject(event: ChangeEvent, subscription: UserSubscription) -> str:
    band = _score_band(event.significance_score)
    topic = (event.topic or "regulatory").replace("_", " ")
    label = subscription.label or "alert"
    # Compact, scannable. Inbox previews cut at ~60 chars.
    return f"[{band}] {topic}: {label}"


def _render_html(
    alert: Alert,
    event: ChangeEvent,
    subscription: UserSubscription,
) -> str:
    s = get_settings()
    base = s.PUBLIC_BASE_URL.rstrip("/")
    inbox_url = f"{base}/api/alerts?email={html.escape(subscription.user_email)}"
    source_url = html.escape(event.source_url or "")
    summary = html.escape(event.summary or "No summary available.")
    topic = html.escape((event.topic or "other").replace("_", " "))
    change_type = html.escape(event.change_type or "—")
    band = _score_band(event.significance_score)
    score = (
        f"{event.significance_score:.2f}"
        if event.significance_score is not None else "—"
    )
    origins = html.escape(_fmt_list(event.origin_countries))
    dests = html.escape(_fmt_list(event.destination_countries))
    flow = html.escape(event.trade_flow_direction or "—")
    matched = html.escape(_fmt_list(alert.matched_keywords))

    # M5c — if the scorer attributed a specific sentence to this change,
    # render it as a blockquote beneath the summary. When the quote
    # was deterministically located in the source we add a small
    # "verified" hint; otherwise we still show it but label it as an
    # LLM attribution (no green-checkmark reassurance).
    trigger_block = ""
    if event.trigger_quote:
        quote_text = html.escape(event.trigger_quote)
        verified = event.trigger_span_start is not None
        label = (
            "From the source document:"
            if verified
            else "The model attributed this change to:"
        )
        border_color = "#0a66c2" if verified else "#d0a060"
        trigger_block = f"""
  <div style="margin:16px 0; font-size:12px; color:#666;">{label}</div>
  <blockquote style="margin:0 0 16px 0; padding:10px 14px;
                     border-left:3px solid {border_color}; background:#fafafa;
                     color:#222; font-style:italic; line-height:1.5;">
    &ldquo;{quote_text}&rdquo;
  </blockquote>"""

    return f"""\
<!doctype html>
<html><body style="font-family: -apple-system, Segoe UI, Arial, sans-serif;
                    color:#111; max-width:640px; margin:0 auto; padding:24px;">
  <h2 style="margin:0 0 8px 0; font-size:18px;">
    Regulatory change detected — <span style="text-transform:uppercase;">{band}</span>
  </h2>
  <p style="color:#555; font-size:13px; margin:0 0 20px 0;">
    Subscription: <strong>{html.escape(subscription.label)}</strong> &middot;
    score {score} &middot; {change_type}
  </p>

  <p style="font-size:15px; line-height:1.45;">{summary}</p>
{trigger_block}
  <table style="font-size:13px; color:#333; margin:16px 0; border-collapse:collapse;">
    <tr><td style="padding:2px 12px 2px 0; color:#777;">Topic</td><td>{topic}</td></tr>
    <tr><td style="padding:2px 12px 2px 0; color:#777;">Trade flow</td><td>{flow}</td></tr>
    <tr><td style="padding:2px 12px 2px 0; color:#777;">Origin</td><td>{origins}</td></tr>
    <tr><td style="padding:2px 12px 2px 0; color:#777;">Destination</td><td>{dests}</td></tr>
    <tr><td style="padding:2px 12px 2px 0; color:#777;">Matched keywords</td><td>{matched}</td></tr>
  </table>

  <p style="margin:24px 0;">
    <a href="{source_url}"
       style="background:#0a66c2; color:#fff; text-decoration:none;
              padding:10px 16px; border-radius:4px; font-size:14px;">
      View source document
    </a>
  </p>

  <p style="color:#999; font-size:12px; margin-top:32px;">
    You're receiving this because your subscription
    &ldquo;{html.escape(subscription.label)}&rdquo; matched this change.
    View your <a href="{inbox_url}" style="color:#0a66c2;">alert inbox</a>.
  </p>
</body></html>
"""


def _render_text(
    alert: Alert,
    event: ChangeEvent,
    subscription: UserSubscription,
) -> str:
    band = _score_band(event.significance_score)
    score = (
        f"{event.significance_score:.2f}"
        if event.significance_score is not None else "—"
    )

    trigger_block = ""
    if event.trigger_quote:
        verified = event.trigger_span_start is not None
        label = (
            "From the source document:"
            if verified
            else "Model-attributed citation (unverified):"
        )
        trigger_block = f"\n{label}\n> {event.trigger_quote}\n"

    return f"""\
Regulatory change detected — {band.upper()}

Subscription: {subscription.label}
Score: {score}  |  Change type: {event.change_type or '-'}  |  Topic: {event.topic or '-'}
Trade flow: {event.trade_flow_direction or '-'}
Origin: {_fmt_list(event.origin_countries)}
Destination: {_fmt_list(event.destination_countries)}
Matched keywords: {_fmt_list(alert.matched_keywords)}

Summary:
{event.summary or 'No summary available.'}
{trigger_block}
Source document:
{event.source_url}

You're receiving this because your subscription matched this change.
"""


# ── Notifier ─────────────────────────────────────────────────────────────────

class EmailNotifier:
    """Delivers alerts over SMTP. Config via settings.SMTP_*.

    Constructs one EmailMessage per alert (no batching). Opens a fresh
    SMTP connection per send — simple and safe against long-lived
    connection drops on a worker. If you push volume high enough to
    care about connection reuse, move to a connection pool later.
    """

    channel = "email"

    def send(
        self,
        *,
        alert: Alert,
        event: ChangeEvent,
        subscription: UserSubscription,
    ) -> None:
        s = get_settings()
        if not s.SMTP_HOST:
            raise NotifierError("SMTP_HOST is not configured")

        to_addr = subscription.channel_target or subscription.user_email
        if not to_addr:
            raise NotifierError("no recipient address on subscription")

        msg = EmailMessage()
        msg["From"] = (
            f"{s.SMTP_FROM_NAME} <{s.SMTP_FROM}>"
            if s.SMTP_FROM_NAME else s.SMTP_FROM
        )
        msg["To"] = to_addr
        msg["Subject"] = _render_subject(event, subscription)
        msg.set_content(_render_text(alert, event, subscription))
        msg.add_alternative(
            _render_html(alert, event, subscription),
            subtype="html",
        )

        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(
                s.SMTP_HOST,
                s.SMTP_PORT,
                timeout=s.SMTP_TIMEOUT_SECONDS,
            ) as smtp:
                smtp.ehlo()
                if s.SMTP_USE_TLS:
                    smtp.starttls(context=ctx)
                    smtp.ehlo()
                if s.SMTP_USER and s.SMTP_PASSWORD:
                    smtp.login(s.SMTP_USER, s.SMTP_PASSWORD)
                smtp.send_message(msg)
        except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
            # Wrap into a single error type so callers don't have to
            # juggle half a dozen stdlib exceptions. Keep the class
            # name so logs can distinguish transient vs auth vs DNS.
            raise NotifierError(
                f"{exc.__class__.__name__}: {exc}"
            ) from exc

        log.info(
            "alert_email_sent",
            alert_id=str(alert.id),
            to=to_addr,
            subject=msg["Subject"],
        )

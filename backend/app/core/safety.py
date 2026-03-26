from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.core.errors import SafetyBlockedError


@dataclass(slots=True)
class SafetyDecision:
    allowed: bool
    reason: str | None = None
    code: str | None = None


def evaluate_user_message(message: str, settings: Settings) -> SafetyDecision:
    if not settings.safety_guard_enabled:
        return SafetyDecision(allowed=True)
    text = (message or "").strip()
    lowered = text.lower()
    if len(text) > settings.safety_max_input_chars:
        return SafetyDecision(
            allowed=False,
            reason="Your message is too long. Please shorten it and try again.",
            code="SAFETY_INPUT_TOO_LARGE",
        )
    for token in settings.safety_blocked_terms_list:
        if token and token in lowered:
            if not settings.safety_guard_strict_block:
                return SafetyDecision(
                    allowed=True,
                    reason="Matched safety pattern in monitor mode",
                    code="SAFETY_MONITOR_MATCH",
                )
            return SafetyDecision(
                allowed=False,
                reason=(
                    "I can't help with that request because it appears to bypass safety "
                    "or request harmful content."
                ),
                code="SAFETY_PROMPT_INJECTION_OR_HARM",
            )
    return SafetyDecision(allowed=True)


def enforce_user_message_safety(message: str, settings: Settings) -> None:
    decision = evaluate_user_message(message, settings)
    if decision.allowed:
        return
    raise SafetyBlockedError(
        decision.reason or "Request blocked by safety policy",
        code=decision.code or "SAFETY_BLOCKED",
    )


def evaluate_email_send_risk(
    *,
    recipient: str,
    subject: str,
    body: str,
    settings: Settings,
) -> SafetyDecision:
    lowered = f"{subject}\n{body}".lower()
    domain = recipient.split("@")[-1].strip().lower() if "@" in recipient else ""
    if domain in set(settings.send_email_blocked_domains_list):
        return SafetyDecision(
            allowed=False,
            reason="Sending to that domain is blocked by policy.",
            code="SAFETY_EMAIL_DOMAIN_BLOCKED",
        )
    allowed_domains = set(settings.send_email_allowed_domains_list)
    if allowed_domains and domain not in allowed_domains:
        return SafetyDecision(
            allowed=False,
            reason="Recipient domain is not in the approved allow-list.",
            code="SAFETY_EMAIL_DOMAIN_NOT_ALLOWED",
        )
    for token in settings.safety_email_blocked_terms_list:
        if token and token in lowered:
            return SafetyDecision(
                allowed=False,
                reason="Email content appears high risk and was blocked.",
                code="SAFETY_EMAIL_CONTENT_BLOCKED",
            )
    return SafetyDecision(allowed=True)

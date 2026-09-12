"""Outbound email, behind a swappable sender.

No third-party email service is integrated, deliberately. The default sender
writes the message to the application log, so password reset and email
verification work end to end on a fresh checkout with nothing to sign up for
and no key to configure. Point `EMAIL_BACKEND=smtp` at any SMTP server -
corporate relay, self-hosted, or a provider's SMTP bridge - and the same
code delivers for real.

Sending never raises to the caller. A reset link that fails to send must not
turn into a 500 that tells an attacker the address exists, and must not roll
back the token that was just issued.
"""
from __future__ import annotations

import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage

from app.core.config import get_settings
from app.core.logging import get_logger, log_extra

logger = get_logger("app.email")


class EmailSender(ABC):
    @abstractmethod
    def send(self, to: str, subject: str, body: str) -> None:
        """Deliver one message. Implementations must not raise."""


class ConsoleEmailSender(EmailSender):
    """Logs the message instead of sending it.

    The default, so the flows are usable in development. The body contains a
    single-use link, which is why this is unsuitable for production - the
    startup log says so explicitly when it is active.
    """

    def send(self, to: str, subject: str, body: str) -> None:
        logger.info(
            "Email (console backend - not delivered)",
            extra=log_extra(to=to, subject=subject),
        )
        # Printed rather than logged at INFO with the body inline, so the
        # link is easy to copy from a terminal during development.
        print(f"\n--- EMAIL to {to} ---\nSubject: {subject}\n\n{body}\n--- end ---\n")


class SMTPEmailSender(EmailSender):
    def send(self, to: str, subject: str, body: str) -> None:
        settings = get_settings()
        message = EmailMessage()
        message["From"] = settings.email_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        try:
            if settings.smtp_use_ssl:
                server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15)
            else:
                server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
            with server:
                if settings.smtp_use_tls and not settings.smtp_use_ssl:
                    server.starttls()
                if settings.smtp_username:
                    server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(message)
            logger.info("Email sent", extra=log_extra(to=to, subject=subject))
        except Exception:
            # Never the credentials, never the body - both are in scope here.
            logger.exception("Failed to send email", extra=log_extra(to=to, subject=subject))


def get_email_sender() -> EmailSender:
    if get_settings().email_backend.lower() == "smtp":
        return SMTPEmailSender()
    return ConsoleEmailSender()

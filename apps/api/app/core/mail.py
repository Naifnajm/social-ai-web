"""E-mail sending (SMTP, or printed to the log when SMTP is not configured — and captured in tests)."""
import logging
import smtplib
from email.message import EmailMessage

from .config import settings

_logger = logging.getLogger(__name__)
OUTBOX: list[EmailMessage] = []  # filled in tests / console mode


def send_mail(to: list[str] | str, subject: str, html: str, text: str | None = None,
              attachments: list[tuple[str, bytes, str]] | None = None) -> None:
    """``attachments``: list of (filename, content, mimetype)."""
    recipients = [to] if isinstance(to, str) else list(to)
    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(text or "This message needs an HTML-capable mail client.")
    message.add_alternative(html, subtype="html")
    for filename, content, mimetype in attachments or []:
        maintype, _, subtype = mimetype.partition("/")
        message.add_attachment(content, maintype=maintype, subtype=subtype or "octet-stream", filename=filename)
    if not settings.smtp_host:
        OUTBOX.append(message)
        _logger.info("E-mail (console) to %s: %s", message["To"], subject)
        return
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_tls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)

import os
import smtplib
import threading
from email.message import EmailMessage


def settings():
    return {
        "host": os.getenv("SMTP_HOST", ""),
        "port": int(os.getenv("SMTP_PORT", "587") or 587),
        "user": os.getenv("SMTP_USER", ""),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "sender": os.getenv("SMTP_FROM", "") or os.getenv("SMTP_USER", ""),
    }


def is_configured():
    s = settings()
    return bool(s["host"] and s["sender"])


def send(to, subject, body):
    s = settings()
    if not is_configured() or not to:
        return False
    msg = EmailMessage()
    msg["From"] = s["sender"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(s["host"], s["port"], timeout=15) as smtp:
        smtp.ehlo()
        if s["port"] != 25:
            smtp.starttls()
            smtp.ehlo()
        if s["user"]:
            smtp.login(s["user"], s["password"])
        smtp.send_message(msg)
    return True


def send_async(to, subject, body):
    if not is_configured() or not to:
        return

    def run():
        try:
            send(to, subject, body)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()

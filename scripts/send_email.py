"""
Envia emails via SMTP (Gmail).
Credenciais lidas de variáveis de ambiente ou GitHub Secrets:
  EMAIL_FROM     – endereço de envio (conta Gmail)
  EMAIL_PASSWORD – App Password do Gmail (não a senha normal)
  EMAIL_TO       – destinatário(s), separados por vírgula
"""

import os
import smtplib
import sys
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from constants import SMTP_HOST, SMTP_PORT


def _build_message(
    subject: str,
    body_html: str,
    from_addr: str,
    to_addrs: list[str],
    images: list[Path] | None = None,
    attachments: list[Path] | None = None,
) -> MIMEMultipart:
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)

    related = MIMEMultipart("related")
    alt = MIMEMultipart("alternative")
    related.attach(alt)
    alt.attach(MIMEText(body_html, "html", "utf-8"))

    if images:
        for img_path in images:
            with open(img_path, "rb") as f:
                img = MIMEImage(f.read())
            img.add_header("Content-ID", f"<{img_path.name}>")
            img.add_header("Content-Disposition", "inline", filename=img_path.name)
            related.attach(img)

    msg.attach(related)

    if attachments:
        for att_path in attachments:
            with open(att_path, "rb") as f:
                data = f.read()
            part = MIMEApplication(data, Name=att_path.name)
            part.add_header("Content-Disposition", "attachment", filename=att_path.name)
            msg.attach(part)

    return msg


def send_email(
    subject: str,
    body_html: str,
    to_addrs: list[str],
    images: list[Path] | None = None,
    attachments: list[Path] | None = None,
):
    from_addr = os.getenv("EMAIL_FROM")
    password = os.getenv("EMAIL_PASSWORD")

    if not from_addr or not password:
        print(
            "[EMAIL] EMAIL_FROM ou EMAIL_PASSWORD não definidos – email ignorado.",
            file=sys.stderr,
        )
        return

    msg = _build_message(subject, body_html, from_addr, to_addrs, images)

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(from_addr, password)
        server.send_message(msg)

    print(f"[EMAIL] Enviado para {', '.join(to_addrs)}: {subject}")


def send_alert_email(subject: str, plain_body: str, to: str):
    """Atalho para alertas simples (texto plano convertido a HTML básico)."""
    html = "<pre>" + plain_body.replace("&", "&amp;").replace("<", "&lt;") + "</pre>"
    to_list = [a.strip() for a in to.split(",")]
    send_email(subject, html, to_list)


if __name__ == "__main__":
    # Teste rápido de envio
    test_to = os.getenv("EMAIL_TO", "")
    if not test_to:
        print("Define EMAIL_TO para teste.")
        sys.exit(1)
    send_alert_email(
        "ET-Spotter – Teste de Email",
        "Se recebeste este email, o envio está a funcionar.",
        test_to,
    )

"""
Envio de email via Resend API.
Substitui Gmail SMTP — a API key não expira automaticamente como os App Passwords do Google.
"""
import os
import resend

def send_email(to: str | list, subject: str, html: str) -> bool:
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print("[SKIP] RESEND_API_KEY não configurada — email não enviado")
        return False
    resend.api_key = api_key
    recipients = [to] if isinstance(to, str) else to
    try:
        r = resend.Emails.send({
            "from": "ET-Spotter <onboarding@resend.dev>",
            "to": recipients,
            "subject": subject,
            "html": html,
        })
        print(f"[OK] Email enviado via Resend: {r['id']}")
        return True
    except Exception as e:
        print(f"[ERRO] Resend: {e}")
        return False

"""
Envia notificações Web Push para todos os subscritores registados.
Subscritores guardados em data/push_subscriptions.json.

Credenciais via variáveis de ambiente:
  VAPID_PRIVATE_KEY – chave privada VAPID (base64url)
  VAPID_PUBLIC_KEY  – chave pública VAPID (base64url, para registo no cliente)
  VAPID_SUBJECT     – mailto: ou URL do proprietário

Geração de chaves VAPID:
  python -c "from py_vapid import Vapid; v=Vapid(); v.generate_keys(); print(v.private_pem().decode()); print(v.public_key.public_bytes_compressed().hex())"
  # ou: npx web-push generate-vapid-keys
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from paths import PUSH_SUBS


def load_subscriptions(path: Path) -> list[dict]:
    """Lê subscritores de push do ficheiro JSON. Devolve [] se não existir."""
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as e:
        print(f"[PUSH] Erro ao ler subscritores: {e}", file=sys.stderr)
        return []


def save_subscriptions(subscriptions: list[dict], path: Path) -> None:
    """Grava lista actualizada de subscritores (ex: após remover expirados)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(subscriptions, f, indent=2)


def send_push_notification(
    subscription: dict,
    payload: dict,
    vapid_private_key: str,
    vapid_claims: dict,
) -> bool:
    """
    Envia uma notificação push para um subscritor.
    Devolve True em caso de sucesso, False caso contrário.
    Se a subscrição expirou (HTTP 410), devolve None para sinalizar remoção.
    """
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        print("[PUSH] pywebpush não instalado — pip install pywebpush", file=sys.stderr)
        return False

    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=vapid_private_key,
            vapid_claims=vapid_claims,
        )
        return True
    except WebPushException as e:
        if e.response is not None and e.response.status_code == 410:
            return None  # subscrição expirada — deve ser removida
        print(f"[PUSH] Erro ao enviar: {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[PUSH] Erro inesperado: {e}", file=sys.stderr)
        return False


def send_alerts_push(alerts: list[dict]) -> int:
    """
    Envia notificação de alertas para todos os subscritores.
    Devolve o número de envios bem-sucedidos.
    """
    private_key = os.getenv("VAPID_PRIVATE_KEY", "")
    subject     = os.getenv("VAPID_SUBJECT", "mailto:admin@et-spotter.local")

    if not private_key:
        print("[PUSH] VAPID_PRIVATE_KEY não definida — push ignorado.", file=sys.stderr)
        return 0

    subscriptions = load_subscriptions(PUSH_SUBS)
    if not subscriptions:
        print("[PUSH] Sem subscritores registados.")
        return 0

    n = len(alerts)
    tickers = ", ".join(a["symbol"] for a in alerts[:3])
    suffix  = "..." if n > 3 else ""
    payload = {
        "title": f"ET-Spotter: {n} alerta{'s' if n != 1 else ''}",
        "body":  f"{tickers}{suffix}",
        "tag":   "et-spotter-alerts",
    }

    vapid_claims = {"sub": subject}
    active       = []
    success      = 0

    for sub in subscriptions:
        result = send_push_notification(sub, payload, private_key, vapid_claims)
        if result is True:
            success += 1
            active.append(sub)
        elif result is False:
            active.append(sub)  # manter — pode ser erro temporário
        # result is None → subscrição expirada, não incluir em active

    if len(active) != len(subscriptions):
        save_subscriptions(active, PUSH_SUBS)
        removed = len(subscriptions) - len(active)
        print(f"[PUSH] {removed} subscri{'ção expirada removida' if removed==1 else 'ções expiradas removidas'}.")

    print(f"[PUSH] {success}/{len(subscriptions)} notificações enviadas.")
    return success


def main() -> None:
    """Teste: envia notificação de teste para todos os subscritores."""
    private_key = os.getenv("VAPID_PRIVATE_KEY", "")
    subject     = os.getenv("VAPID_SUBJECT", "mailto:admin@et-spotter.local")

    if not private_key:
        print("[PUSH] VAPID_PRIVATE_KEY não definida.", file=sys.stderr)
        sys.exit(1)

    subscriptions = load_subscriptions(PUSH_SUBS)
    if not subscriptions:
        print("[PUSH] Sem subscritores. Adiciona subscritores em data/push_subscriptions.json.")
        sys.exit(0)

    payload      = {"title": "ET-Spotter", "body": "Notificação de teste.", "tag": "test"}
    vapid_claims = {"sub": subject}

    for sub in subscriptions:
        result = send_push_notification(sub, payload, private_key, vapid_claims)
        endpoint = sub.get("endpoint", "")[:60]
        status   = "✓" if result is True else ("✗ expirado" if result is None else "✗")
        print(f"  {status}  {endpoint}...")


if __name__ == "__main__":
    main()

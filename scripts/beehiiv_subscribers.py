"""
Busca lista de subscritores ativos do Beehiiv via API v2.
Devolve lista de emails confirmados e ativos.
"""
import os
import requests

def get_active_subscribers() -> list[str]:
    api_key = os.environ.get("BEEHIIV_API_KEY")
    pub_id  = os.environ.get("BEEHIIV_PUB_ID")

    if not api_key or not pub_id:
        print("[SKIP] BEEHIIV_API_KEY ou BEEHIIV_PUB_ID não configurados")
        return []

    url     = f"https://api.beehiiv.com/v2/publications/{pub_id}/subscriptions"
    headers = {"Authorization": f"Bearer {api_key}"}
    params  = {"status": "active", "limit": 100}
    emails  = []

    while url:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code != 200:
            print(f"[ERRO] Beehiiv API: {r.status_code} {r.text[:200]}")
            break
        data   = r.json()
        emails += [s["email"] for s in data.get("data", []) if s.get("email")]
        # paginação
        next_page = data.get("nextCursor") or data.get("next_cursor")
        if next_page:
            params = {"status": "active", "limit": 100, "cursor": next_page}
        else:
            url = None

    print(f"[OK] Beehiiv: {len(emails)} subscritores ativos")
    return emails

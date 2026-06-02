"""
Vercel serverless function — GET /api/scores
Lê scores_latest.csv do repositório GitHub e devolve JSON.
Sem dependências externas além da stdlib.
"""

import csv
import io
import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler

_GITHUB_RAW = (
    "https://raw.githubusercontent.com/{owner}/{repo}/{branch}/"
    "data/reports/scores_latest.csv"
)
_NUMERIC = {
    "score", "score_pct", "ret_1d", "ret_5d", "ret_21d", "ret_63d",
    "ret_126d", "ret_252d", "rsi", "adx", "vol_21", "drawdown",
    "sharpe_63", "calmar_63", "rs_ratio", "rs_mom_21", "rs_mom_63",
}
_INT = {"trend_sma", "macd_bullish", "above_sma200", "rs_positive"}


def _parse_csv(content: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(content))
    rows = []
    for row in reader:
        clean: dict = {}
        for k, v in row.items():
            if k in _NUMERIC:
                try:
                    clean[k] = float(v)
                except (ValueError, TypeError):
                    clean[k] = None
            elif k in _INT:
                try:
                    clean[k] = int(float(v))
                except (ValueError, TypeError):
                    clean[k] = None
            else:
                clean[k] = v
        rows.append(clean)
    return rows


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        owner  = os.environ.get("GITHUB_OWNER", "")
        repo   = os.environ.get("GITHUB_REPO",  "")
        branch = os.environ.get("GITHUB_BRANCH", "main")
        token  = os.environ.get("GITHUB_TOKEN", "")

        if not owner or not repo:
            self._respond(500, {"ok": False, "error": "GITHUB_OWNER / GITHUB_REPO not set"})
            return

        url = _GITHUB_RAW.format(owner=owner, repo=repo, branch=branch)
        req = urllib.request.Request(url)
        if token:
            req.add_header("Authorization", f"token {token}")

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read().decode("utf-8")
        except Exception as e:
            self._respond(502, {"ok": False, "error": f"upstream fetch failed: {e}"})
            return

        rows = _parse_csv(content)
        self._respond(200, {"ok": True, "count": len(rows), "data": rows})

    def _respond(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # suppress default access log
        pass

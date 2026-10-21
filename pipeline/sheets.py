"""Talk to the Google Sheet through the Apps Script web app (token-protected)."""
import os

import requests


def _url():
    return os.environ["GAS_WEBHOOK_URL"]


def _token():
    return os.environ["SECRET_TOKEN"]


def get_suppression():
    """Licenses and domains already handled (so nothing is ever contacted twice)."""
    try:
        r = requests.get(_url(), params={"action": "suppress", "token": _token()}, timeout=60)
        d = r.json()
        if "error" in d:
            raise RuntimeError(d["error"])
        return {"licenses": set(d.get("licenses", [])), "domains": set(d.get("domains", []))}
    except Exception as e:
        print("WARNING: could not read suppression list:", e)
        return {"licenses": set(), "domains": set()}


def post_rows(rows, summary=None):
    r = requests.post(_url(), timeout=120, json={"token": _token(), "rows": rows, "summary": summary})
    print("Sheet response:", r.status_code, r.text[:200])
    return r.ok


def get_bounces():
    """Emails you pasted into the Bounces tab: never used again."""
    try:
        r = requests.get(_url(), params={"action": "bounces", "token": _token()}, timeout=60)
        return {e.lower() for e in r.json().get("emails", [])}
    except Exception as e:
        print("WARNING: could not read bounces:", e)
        return set()


def ping():
    r = requests.get(_url(), params={"action": "ping", "token": _token()}, timeout=60)
    return r.json()


def export():
    r = requests.get(_url(), params={"action": "export", "token": _token()}, timeout=120)
    return r.json()

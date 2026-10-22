"""Free-tier search APIs with a daily cap. Returns results WITH snippets, so one search can
give both the website and the revenue/employee figures. API formats come from each provider's
public docs; preflight.py tests each key before the real run."""
import os
import re
import threading
from urllib.parse import urlparse

from . import config
from .web import domain_of

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,10}")


class Searcher:
    def __init__(self, cap):
        self.cap = cap
        self.used = 0
        self.lock = threading.Lock()
        self.fail = {}
        self.providers = []
        for name, env in (("serper", "SERPER_API_KEY"), ("tavily", "TAVILY_API_KEY"), ("exa", "EXA_API_KEY")):
            if os.getenv(env):
                self.providers.append((name, os.environ[env]))

    def left(self):
        return self.cap - self.used

    def _call(self, name, key, q):
        import requests
        if name == "serper":
            r = requests.post("https://google.serper.dev/search", timeout=15,
                              headers={"X-API-KEY": key, "Content-Type": "application/json"},
                              json={"q": q, "num": 8, "gl": "us"})
            return [{"url": x.get("link"), "title": x.get("title", ""), "snippet": x.get("snippet", "")}
                    for x in r.json().get("organic", [])]
        if name == "tavily":
            r = requests.post("https://api.tavily.com/search", timeout=20,
                              headers={"Authorization": f"Bearer {key}"},
                              json={"query": q, "max_results": 8})
            return [{"url": x.get("url"), "title": x.get("title", ""), "snippet": x.get("content", "")}
                    for x in r.json().get("results", [])]
        if name == "exa":
            r = requests.post("https://api.exa.ai/search", timeout=20,
                              headers={"x-api-key": key, "Content-Type": "application/json"},
                              json={"query": q, "numResults": 8, "contents": {"text": True}})
            return [{"url": x.get("url"), "title": x.get("title", ""),
                     "snippet": (x.get("text") or "")[:900]} for x in r.json().get("results", [])]
        return []

    def search(self, q):
        """One credit per call. Returns a list of {url,title,snippet}, or [] if nothing/over cap."""
        for name, key in self.providers:
            if self.fail.get(name, 0) >= 5:
                continue
            with self.lock:
                if self.used >= self.cap:
                    return []
                self.used += 1
            try:
                res = self._call(name, key, q)
            except Exception:
                res = []
            if res:
                return res
            self.fail[name] = self.fail.get(name, 0) + 1
        return []

    @staticmethod
    def sites_from(results):
        out, seen = [], set()
        for r in results:
            u = r.get("url")
            if not u:
                continue
            d = domain_of(u)
            if any(d == x or d.endswith("." + x) for x in config.DIRECTORY_DOMAINS) or d in seen:
                continue
            seen.add(d)
            p = urlparse(u)
            out.append(f"{p.scheme}://{p.netloc}")
        return out[:3]

    @staticmethod
    def snippets(results):
        return [f'{r.get("title", "")} {r.get("snippet", "")}' for r in results]

    def company_query(self, rec):
        """Website candidates + snippets (revenue, employees) in ONE credit."""
        res = self.search(f'{rec["company"]} {rec.get("city", "")} {rec["state"]} solar revenue employees')
        return self.sites_from(res), self.snippets(res)

    def places(self, rec):
        """Google Business Profile listings (Serper /places, 1 credit): website, phone, address, reviews.
        Returns a list of dicts: title, address, phone, website, reviews."""
        key = dict(self.providers).get("serper")
        if not key:
            return []
        with self.lock:
            if self.used >= self.cap:
                return []
            self.used += 1
        try:
            import requests
            r = requests.post("https://google.serper.dev/places", timeout=15,
                              headers={"X-API-KEY": key, "Content-Type": "application/json"},
                              json={"q": f'{rec["company"]} {rec.get("city", "")} {rec["state"]}', "gl": "us"})
            out = []
            for x in r.json().get("places", []):
                out.append({"title": x.get("title", ""), "address": x.get("address", ""),
                            "phone": x.get("phoneNumber") or x.get("phone") or "",
                            "website": x.get("website") or "", "reviews": x.get("ratingCount") or 0})
            return out
        except Exception:
            return []

    def owner_query(self, rec):
        """Snippets that may name the owner (LinkedIn titles, directories, news). 1 credit."""
        res = self.search(f'"{rec["company"]}" {rec.get("city", "")} {rec["state"]} owner OR founder OR president')
        return self.snippets(res)

    def domain_emails(self, domain):
        """Emails for this domain that appear anywhere else on the web (1 credit)."""
        res = self.search(f'"@{domain}"')
        found = []
        for r in res:
            for e in _EMAIL.findall(f'{r.get("title", "")} {r.get("snippet", "")}'):
                e = e.lower().strip(".,;:")
                if e.endswith("@" + domain) and e not in found:
                    found.append(e)
        return found

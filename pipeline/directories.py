"""Extra email sources: association, program and chamber directories.
List the pages in data/directories.csv (one URL per row). build_dir_index.py crawls them once
(follows 'next' links) and saves every email it finds, keyed by the email's domain."""
import csv
import json
import re
from urllib.parse import urljoin, urlparse

from . import web


def crawl(url, max_pages=40):
    emails, seen, queue = set(), set(), [url]
    host = urlparse(url).netloc
    while queue and len(seen) < max_pages:
        u = queue.pop(0)
        if u in seen:
            continue
        seen.add(u)
        html = web.fetch(u)
        if not html:
            continue
        for e, _ in web.extract_emails(html):
            emails.add(e)
        for href, label in re.findall(r'(?is)<a\s[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', html):
            full = urljoin(u, href)
            if urlparse(full).netloc == host and re.search(r"(?i)next|page=|/page/|\bmore\b", label + href):
                queue.append(full)
    return emails


def build_index(csv_path="data/directories.csv", out_path="data/dir_index.json"):
    index = {}
    with open(csv_path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            url = (r.get("url") or "").strip()
            if not url or url.startswith("#"):
                continue
            found = crawl(url)
            print(f"{url}: {len(found)} emails")
            for e in found:
                index.setdefault(e.split("@")[1], set()).add(e)
    with open(out_path, "w") as fh:
        json.dump({k: sorted(v) for k, v in index.items()}, fh)
    print(f"Saved {len(index)} domains to {out_path}")


def load_index(path="data/dir_index.json"):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return {}


if __name__ == "__main__":
    build_index()

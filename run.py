"""Daily run (v2): research companies area by area and send only verified, clean rows to the Sheet."""
import csv
import datetime
import os
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from pipeline import areas as areamod
from pipeline import config, directories, sheets, web
from pipeline.search import Searcher
from pipeline.verify import Verifier

ROW_KEYS = ["Label", "Email Status", "Tier", "Score", "Area", "Company", "Website", "Owner Name",
            "Owner Email", "Company Email", "Email Source", "Proof URL", "Area Evidence", "Size Signals",
            "Revenue Est", "State", "City", "Phone", "License", "Notes", "Date"]


class Shared:
    def __init__(self, searcher, verifier, dir_index, big_names, bounces, seen_domains, t0):
        self.lock = threading.Lock()
        self.searcher, self.verifier = searcher, verifier
        self.dir_index, self.big_names, self.bounces = dir_index, big_names, bounces
        self.seen_domains = set(seen_domains)
        self.assigned = set()
        self.t0 = t0

    def time_up(self):
        return (time.time() - self.t0) / 60 > config.MAX_RUNTIME_MIN

    def has_credit(self):
        return self.searcher.left() > 0.1 * self.searcher.cap      # keep a reserve


def read_master():
    with open("data/master.csv", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["state"] in config.STATES]
    for r in rows:
        r["rank"] = int(r.get("rank") or 0)
        r["multistate"] = int(r.get("multistate") or 1)
    rows.sort(key=lambda r: -r["rank"])
    return rows


def read_lines(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return [l.strip().lower() for l in fh if l.strip() and not l.startswith("#")]
    except FileNotFoundError:
        return []


def new_row(rec, area):
    row = {k: "" for k in ROW_KEYS}
    row.update({"Company": rec["company"], "State": rec["state"], "City": rec["city"], "Phone": rec["phone"],
                "License": rec["key"], "Owner Name": rec.get("owner", ""), "Area": area["name"],
                "Date": datetime.date.today().isoformat()})
    return row


def reject(row, why):
    row.update({"Label": "reject", "Notes": why})
    return row


def find_site(rec, sh):
    """Guess domains first (free), then one search that also returns revenue/employee snippets."""
    weak, tried = None, set()

    def check(base, source, snips):
        nonlocal weak
        html = web.fetch(base)
        if not html:
            return None
        ident = web.identity(web.text_of(html), rec)
        if ident["level"] == "strong":
            return (base, html, source, ident, snips)
        if ident["level"] == "weak" and weak is None:
            weak = (base, html, source, ident, snips)
        return None

    for d in web.guess_domains(rec["company"]):
        if d in tried or not web.resolves(d):
            continue
        tried.add(d)
        hit = check("https://" + d, "guess", [])
        if hit:
            return hit
    if sh.has_credit():
        sites, snips = sh.searcher.company_query(rec)
        for base in sites:
            d = web.domain_of(base)
            if d in tried:
                continue
            tried.add(d)
            hit = check(base, "search", snips)
            if hit:
                return hit
    return weak


def ordered_candidates(emails, owner, raw, domain):
    """[(email, 'owner'|'company')], owner email first, own-domain non-role addresses next."""
    o, c = web.classify_emails(emails, owner, raw, domain)
    rest = [a for a, _ in emails if a not in (o, c)]
    rest.sort(key=lambda a: (not a.endswith("@" + domain), a.split("@")[0].split(".")[0] in config.ROLE_PREFIXES))
    out = ([(o, "owner")] if o else []) + ([(c, "company")] if c else []) + [(a, "company") for a in rest]
    return out[:4]


def first_acceptable(cands, sh):
    for addr, kind in cands:
        if addr in sh.bounces:
            continue
        st = sh.verifier.status(addr)
        if st in ("verified", "published_only"):
            return addr, kind, st
    return None


def find_email(rec, domain, pages, owner, sh, snips_ok=True):
    """Source chain: 1 own site, 2 directories, 3 Wayback, 4 search for the domain's emails.
    Stops at the first source that gives an email that passes verification."""
    raw = " ".join(h for _, h in pages)
    cands = []
    for url, h in pages:
        for a, pos in web.extract_emails(h):
            cands.append((a, pos, url))
    hit = first_acceptable(ordered_candidates([(a, p) for a, p, _ in cands], owner, raw, domain), sh)
    if hit:
        proof = next((u for a, _, u in cands if a == hit[0]), pages[0][0])
        return hit + ("own site", proof)
    dir_emails = [e for e in sh.dir_index.get(domain, [])]
    if dir_emails:
        hit = first_acceptable(ordered_candidates([(e, 0) for e in dir_emails], owner, "", domain), sh)
        if hit:
            return hit + ("directory", "data/dir_index.json")
    wb = web.wayback_pages(domain)
    if wb:
        wbraw = " ".join(wb)
        wbc = [(a, p) for h in wb for a, p in web.extract_emails(h)]
        hit = first_acceptable(ordered_candidates(wbc, owner, wbraw, domain), sh)
        if hit:
            return hit + ("wayback", f"https://web.archive.org/web/*/{domain}")
    if sh.has_credit():
        found = sh.searcher.domain_emails(domain)
        hit = first_acceptable(ordered_candidates([(e, 0) for e in found], owner, "", domain), sh)
        if hit:
            return hit + ("web search", f'search: "@{domain}"')
    return None


def fmt_rev(rev):
    if not rev:
        return "unknown"
    return f"${rev[0]:g}M" if rev[0] == rev[1] else f"${rev[0]:g}M-${rev[1]:g}M"


def process(rec, area, sh):
    row = new_row(rec, area)
    name = rec["company"].lower()
    if any(b in name for b in config.NATIONAL_BLOCKLIST):
        return reject(row, "national name")
    site = find_site(rec, sh)
    if not site:
        return reject(row, "no website found")
    base, home_html, source, ident, snips = site
    domain = web.domain_of(base)
    with sh.lock:
        if domain in sh.seen_domains:
            return reject(row, "domain already used")
        sh.seen_domains.add(domain)
    pages, has_team = [(base, home_html)], False
    for url in web.find_pages(home_html, base):
        if len(pages) >= 5:
            break
        h = web.fetch(url)
        if h:
            pages.append((url, h))
            has_team = has_team or "team" in url.lower()
    text = web.text_of(" ".join(h for _, h in pages))
    nat = web.national_flag(rec["company"], text)
    if nat == "yes":
        return reject(row, "national company")
    ok, why = web.pure_installer(text)
    if not ok:
        return reject(row, why)
    ev = "licensed address in area"
    wev = areamod.website_evidence(text, area)
    if wev:
        ev += "; " + wev
    owner = web.extract_owner(text) or rec.get("owner", "")
    pts, tier, why_score = web.score(text, has_team)
    row.update({"Website": base, "Owner Name": owner, "Score": pts, "Tier": tier, "Area Evidence": ev,
                "Notes": why_score})
    got = find_email(rec, domain, pages, owner, sh)
    if not got:
        row["Label"] = "nomail"
        return row
    addr, kind, status, esource, proof = got
    # size: one search for survivors, unless the website search already returned snippets
    if not snips and sh.has_credit():
        snips = Searcher.snippets(sh.searcher.search(
            f'{rec["company"]} {rec["city"]} {rec["state"]} solar revenue employees'))
    rev = web.parse_revenue(snips, rec["company"])
    emp = web.parse_employees(snips, rec["company"])
    sig = web.big_signals(rec, text, nat, rev, emp, sh.big_names)
    row.update({"Revenue Est": fmt_rev(rev), "Size Signals": "; ".join(sig)})
    if len(sig) >= config.BIG_EXCLUDE_AT:
        return reject(row, "too big: " + ", ".join(sig))
    if config.MIN_REVENUE_M and rev and rev[1] < config.MIN_REVENUE_M:
        return reject(row, "below revenue floor")
    row.update({"Owner Email" if kind == "owner" else "Company Email": addr,
                "Email Status": status, "Email Source": esource, "Proof URL": proof})
    green = status == "verified" and ident["level"] == "strong" and not sig and kind == "owner"
    row["Label"] = "green" if green else "yellow"
    return row


def safe_process(rec, area, sh):
    try:
        return process(rec, area, sh)
    except Exception as e:
        row = new_row(rec, area)
        row.update({"Label": "error", "Notes": str(e)[:120]})
        return row


def run_area(area, queue, quota, sh, ex, stats):
    rows, passed, idx = [], 0, 0
    while passed < quota and idx < len(queue) and not sh.time_up():
        batch = []
        while len(batch) < config.WORKERS * 2 and idx < len(queue):
            rec = queue[idx]
            idx += 1
            with sh.lock:
                if rec["key"] in sh.assigned:
                    continue
                sh.assigned.add(rec["key"])
            batch.append(rec)
        for row in ex.map(lambda r: safe_process(r, area, sh), batch):
            rows.append(row)
            stats[row["Label"]] += 1
            if row["Label"] in ("green", "yellow"):
                passed += 1
            if config.LIMIT_COMPANIES and sum(stats.values()) >= config.LIMIT_COMPANIES:
                return rows, passed
    return rows, passed


def main():
    t0 = time.time()
    master = read_master()
    sup = sheets.get_suppression()
    all_areas = areamod.load_areas()
    if not all_areas:
        raise SystemExit("data/areas.csv has no areas. Add your sample areas first.")
    queues = areamod.build_queues(master, all_areas, sup["licenses"])
    forced = [x.strip() for x in os.getenv("AREAS", "").split(",") if x.strip()]
    today = areamod.pick_areas(all_areas, queues, k=3, forced=forced)
    if not today:
        raise SystemExit("No area has companies left. Check data/areas.csv and data/master.csv.")
    verifier = Verifier()
    searcher = Searcher(config.SEARCH_DAILY_CAP)
    sh = Shared(searcher, verifier, directories.load_index(), read_lines("data/big_names.txt"),
                sheets.get_bounces(), sup["domains"], t0)
    print(f"Areas today: {[a['id'] for a in today]} | verify mode: {verifier.mode} | "
          f"search providers: {len(searcher.providers)} | queue sizes: "
          f"{ {a['id']: len(queues[a['id']]) for a in today} }")
    quota = config.TARGET_SENDABLE // len(today)
    rows, stats, per_area = [], Counter(), []
    with ThreadPoolExecutor(config.WORKERS) as ex:
        for a in today:
            r, p = run_area(a, queues[a["id"]], quota, sh, ex, stats)
            rows += r
            per_area.append(f'{a["id"]} {p}/{quota}')
            print(f'  {a["id"]}: {p}/{quota} passed, {len(r)} researched, searches used {searcher.used}')
    # a few near-misses for you to look up by hand (best tier first)
    near = sorted([r for r in rows if r["Label"] == "nomail"],
                  key=lambda r: (r["Tier"] != "A", -(r["Score"] or 0), not r["Owner Name"]))
    for r in near[:config.MANUAL_CAP]:
        r["Label"] = "manual"
    reasons = Counter(r["Notes"].split(":")[0] for r in rows if r["Label"] == "reject")
    summary = {"Date": datetime.date.today().isoformat(), "Processed": len(rows),
               "Green": stats["green"], "Yellow": stats["yellow"], "Manual": min(len(near), config.MANUAL_CAP),
               "Rejected": stats["reject"], "Errors": stats["error"], "Searches": searcher.used,
               "Minutes": round((time.time() - t0) / 60, 1), "Areas": "; ".join(per_area),
               "Top reject reasons": ", ".join(f"{k} {v}" for k, v in reasons.most_common(4))}
    print("SUMMARY", summary)
    if rows:
        sheets.post_rows(rows, summary)


if __name__ == "__main__":
    main()

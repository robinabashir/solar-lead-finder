"""Steps 2-4: find the company's site, read it, pull emails and the owner name."""
import html as htmllib
import re
import socket
import time
from urllib.parse import urljoin, urlparse

from . import config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
_last_hit = {}
_hit_lock = __import__("threading").Lock()


# ---------------------------------------------------------------- fetching
def fetch(url, timeout=12, max_bytes=1_500_000):
    """Polite plain-HTTP fetch. Returns HTML text or None."""
    import requests
    host = urlparse(url).netloc
    with _hit_lock:                       # one request per second per website, even with many workers
        now = time.time()
        slot = max(now, _last_hit.get(host, 0) + config.REQUEST_DELAY_SEC)
        _last_hit[host] = slot
    if slot > now:
        time.sleep(slot - now)
    headers = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
               "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}
    for verify in (True, False):          # second try ignores a broken certificate (small business sites)
        try:
            r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True,
                             stream=True, verify=verify)
            if r.status_code >= 400:
                return None
            if "html" not in r.headers.get("Content-Type", "html").lower():
                return None
            data = r.raw.read(max_bytes, decode_content=True)
            return data.decode(r.encoding or "utf-8", errors="replace")
        except requests.exceptions.SSLError:
            continue
        except Exception:
            return None
    return None


def fetch_any(url):
    """Try https, then the www / non-www twin, then http. Returns (html, working_base_url) or (None, None)."""
    p = urlparse(url if "//" in url else "https://" + url)
    host = p.netloc
    bare = host[4:] if host.startswith("www.") else host
    for u in (f"https://{host}", f"https://www.{bare}" if host == bare else f"https://{bare}", f"http://{host}"):
        html = fetch(u)
        if html:
            return html, u
    return None, None


def text_of(html):
    html = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html or "")
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", htmllib.unescape(html)).strip()


# ---------------------------------------------------------------- domains
_SUFFIX = {"llc", "inc", "corp", "corporation", "co", "ltd", "company", "incorporated", "lp", "pllc"}


def guess_domains(company, limit=6):
    name = re.sub(r"&", " and ", company.lower())
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    toks = [t for t in name.split() if t not in _SUFFIX]
    if not toks:
        return []
    core = [t for t in toks if t != "solar"]
    cands = []
    base = "".join(toks)
    cands += [base + ".com", "-".join(toks) + ".com"]
    if core and "solar" not in toks:
        cands.append("".join(core) + "solar.com")
    if core and len(core) != len(toks):
        cands.append("".join(core) + ".com")
    cands += [base + "llc.com", base + "inc.com"]
    seen, out = set(), []
    for c in cands:
        if c not in seen and 5 < len(c) < 45:
            seen.add(c)
            out.append(c)
    return out[:limit]


def resolves(domain):
    try:
        socket.setdefaulttimeout(4)
        socket.gethostbyname(domain)
        return True
    except Exception:
        return False


def base_url(url):
    p = urlparse(url if "//" in url else "https://" + url)
    return f"{p.scheme}://{p.netloc}"


def domain_of(url):
    d = urlparse(url if "//" in url else "https://" + url).netloc.lower()
    return d[4:] if d.startswith("www.") else d


# ---------------------------------------------------------------- identity check
_STOP = {"llc", "inc", "corp", "co", "ltd", "company", "the", "and", "of", "solar", "energy",
         "power", "systems", "services", "electric", "electrical", "home", "group"}


def identity(text, rec, domain=""):
    """What on the page proves it is THIS licensed company?
    strong = license number or phone number on the page.
    weak   = company name plus its city, ZIP or county, or the web address is the company name."""
    low = text.lower()
    alnum = re.sub(r"[^a-z0-9]", "", low)
    digits = re.sub(r"\D", "", text)
    lic = re.sub(r"[^a-z0-9]", "", str(rec.get("license", "")).lower())
    lic_hit = len(lic) >= 5 and lic in alnum
    ph = rec.get("phone", "")
    phone_hit = len(ph) == 10 and ph in digits
    city = (rec.get("city") or "").lower()
    city_hit = bool(city) and city in low
    zip_hit = bool(rec.get("zip")) and rec["zip"] in re.findall(r"\b\d{5}\b", text)
    county = (rec.get("county") or "").lower()
    county_hit = bool(county) and (county + " county") in low
    toks = [t for t in re.sub(r"[^a-z0-9 ]", " ", rec.get("company", "").lower()).split() if t not in _STOP]
    if not toks:
        toks = re.sub(r"[^a-z0-9 ]", " ", rec.get("company", "").lower()).split()
    need = len(toks) if len(toks) < 3 else -(-2 * len(toks) // 3)       # 3+ words: two thirds must match
    name_hit = bool(toks) and sum(1 for t in toks if t in low) >= need
    base = re.sub(r"[^a-z0-9]", "", domain.lower().rsplit(".", 1)[0]) if domain else ""
    full = re.sub(r"[^a-z0-9]", "", " ".join(t for t in re.sub(r"[^a-z0-9 ]", " ", rec.get("company", "").lower()).split()
                                              if t not in {"llc", "inc", "corp", "co", "ltd", "company"}))
    domain_hit = bool(base) and (base == full or (len(toks) >= 2 and all(t in base for t in toks)))
    where = city_hit or zip_hit or county_hit
    level = "strong" if (lic_hit or phone_hit) else (
        "weak" if ((name_hit and where) or (domain_hit and "solar" in low)) else "none")
    return {"license": lic_hit, "phone": phone_hit, "city": city_hit, "zip": zip_hit, "county": county_hit,
            "name": name_hit, "domain": domain_hit, "level": level}


# ---------------------------------------------------------------- pages
_PAGE_WORDS = ("contact", "about", "team", "our-story", "leadership", "who-we-are", "meet", "privacy", "terms")


def find_pages(home_html, home_url, limit=3):
    base = base_url(home_url)
    host = urlparse(base).netloc
    found = []
    for href, label in re.findall(r'(?is)<a\s[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', home_html or ""):
        full = urljoin(home_url, href.strip())
        if urlparse(full).netloc != host or full.rstrip("/") == home_url.rstrip("/"):
            continue
        hay = (href + " " + re.sub(r"<[^>]+>", "", label)).lower()
        if any(w in hay for w in _PAGE_WORDS) and full not in found:
            found.append(full)
    for path in ("/contact", "/contact-us", "/about", "/about-us"):   # fallbacks
        u = base + path
        if u not in found:
            found.append(u)
    return found[:limit + 3]


# ---------------------------------------------------------------- emails
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,10}")
_JUNK = ("example.", "sentry", "wixpress", "yourdomain", "domain.com", "email.com", "u003e",
         ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", "godaddy", "schema.org", "wordpress")


def decode_cf(hexstr):
    try:
        key = int(hexstr[:2], 16)
        return "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))
    except Exception:
        return ""


def extract_emails(html):
    """Return list of (email, position_in_text). Handles mailto, obfuscated and Cloudflare-hidden emails."""
    raw = htmllib.unescape(html or "")
    raw = re.sub(r"(?i)\s*[\[\(\{]\s*at\s*[\]\)\}]\s*", "@", raw)
    raw = re.sub(r"(?i)\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", ".", raw)
    found = []
    for m in re.finditer(r'data-cfemail=["\']([0-9a-fA-F]+)["\']', raw):
        e = decode_cf(m.group(1))
        if e:
            found.append((e, m.start()))
    for m in _EMAIL_RE.finditer(raw):
        found.append((m.group(0), m.start()))
    out, seen = [], set()
    for e, pos in found:
        e = e.strip(".,;:").lower()
        if any(j in e for j in _JUNK) or e in seen:
            continue
        seen.add(e)
        out.append((e, pos))
    return out


# ---------------------------------------------------------------- owner name
_NAME = r"([A-Z][a-z]{1,15}(?:\s[A-Z]\.?)?(?:\s(?:Mc|Mac|O')?[A-Z][a-zA-Z'\-]{1,18}){1,2})"
_TITLE = r"(Owner|Co-Owner|Founder|Co-Founder|President|CEO|Chief Executive Officer|Principal)"
_BAD = {"solar", "energy", "power", "services", "company", "contact", "about", "our", "the", "team",
        "home", "free", "quote", "meet", "licensed", "call", "us", "and", "of", "for", "your", "get",
        "owner", "founder", "president", "manager", "mission", "story", "panel", "panels", "systems"}


def _ok_name(n):
    toks = [t.lower().strip(".") for t in n.split()]
    return 2 <= len(toks) <= 3 and not any(t in _BAD for t in toks)


def extract_owner(text):
    # "John Smith, Owner"  /  "John Smith - Founder & CEO"
    for m in re.finditer(rf"{_NAME}\s*[,\-–—|:]\s*(?:Founder\s*(?:&|and)\s*)?{_TITLE}\b", text):
        if _ok_name(m.group(1)):
            return m.group(1).strip()
    # "Owner: John Smith"  /  "President - John Smith"
    for m in re.finditer(rf"{_TITLE}\s*[:\-–—|,]\s*{_NAME}", text):
        if _ok_name(m.group(2)):
            return m.group(2).strip()
    return ""


def classify_emails(emails, owner, raw_html, site_domain):
    """Split into owner email and company email. emails = [(addr, pos)]."""
    first = last = ""
    if owner:
        parts = owner.lower().split()
        first, last = parts[0], parts[-1]
    owner_email, company_email = "", ""
    low = (raw_html or "").lower()
    for addr, pos in emails:
        local, _, dom = addr.partition("@")
        is_role = local.split(".")[0] in config.ROLE_PREFIXES
        name_match = bool(first and (first in local or (len(last) > 2 and last in local)
                                     or (first[0] + last) in local))
        near_title = any(t.lower() in low[max(0, pos - 160):pos + 160] for t in ("owner", "founder", "president", "ceo"))
        if not is_role and (name_match or near_title) and not owner_email:
            owner_email = addr
        elif not company_email and (dom.endswith(site_domain) or site_domain.endswith(dom)):
            company_email = addr
        elif not company_email and not owner_email:
            company_email = addr
    return owner_email, company_email


# ---------------------------------------------------------------- flags and score
def national_flag(company, text):
    n = company.lower()
    if any(b in n for b in config.NATIONAL_BLOCKLIST):
        return "yes"
    low = text.lower()
    hits = sum(1 for p in config.NATIONAL_PHRASES if p in low)
    states = set(re.findall(r"\b(?:alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|"
                            r"florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|"
                            r"maine|maryland|massachusetts|michigan|minnesota|mississippi|missouri|montana|"
                            r"nebraska|nevada|new hampshire|new jersey|new mexico|new york|north carolina|"
                            r"north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|south carolina|"
                            r"south dakota|tennessee|texas|utah|vermont|virginia|washington|west virginia|"
                            r"wisconsin|wyoming)\b", low))
    if hits >= 2 or len(states) >= 12:
        return "yes"
    if hits == 1 or len(states) >= 7:
        return "maybe"
    return "no"


def counties_mentioned(text):
    return {c.lower() for c in re.findall(r"\b([A-Z][a-z]+(?:[ \-][A-Z][a-z]+)?) County\b", text)}


def score(text, has_team_page):
    low = text.lower()
    pts, why = 0, []
    if any(w in low for w in ("residential", "homeowner", "home solar", "your home")):
        pts += 3; why.append("residential")
    if any(w in low for w in ("free quote", "free estimate", "get a quote", "financing", "free consultation")):
        pts += 2; why.append("quote/financing")
    titles = len(re.findall(r"\b(owner|manager|installer|technician|electrician|consultant|designer|engineer)\b", low))
    if has_team_page and titles >= 4:
        pts += 2; why.append("team")
    if any(w in low for w in ("careers", "we're hiring", "we are hiring", "join our team", "now hiring")):
        pts += 1; why.append("hiring")
    if len(counties_mentioned(text)) >= 3:
        pts += 1; why.append("multi-county")
    tier = "A" if pts >= 6 else ("B" if pts >= 3 else "C")
    return pts, tier, ", ".join(why)


# ---------------------------------------------------------------- v2: pure installer screen
def pure_installer(text):
    """Is this a company that installs solar for homes? Returns (ok, reason)."""
    low = text.lower()
    resid = any(w in low for w in ("residential", "homeowner", "home solar", "your home", "your house"))
    if low.count("solar") < 3 or "install" not in low:
        return False, "no solar install evidence"
    if any(b in low for b in ("utility-scale", "utility scale", "we manufacture", "manufacturer of",
                              "wholesale distributor", "distributor of solar")) and not resid:
        return False, "not a residential installer"
    commercial = "commercial and industrial" in low or "commercial solar" in low or "c&i" in low
    if commercial and not resid:
        return False, "commercial only"
    return True, ""


# ---------------------------------------------------------------- v2: size signals from search snippets
_UNIT = {"billion": 1000.0, "bn": 1000.0, "b": 1000.0, "million": 1.0, "mm": 1.0, "m": 1.0,
         "thousand": 0.001, "k": 0.001}


def _num(x):
    try:
        return float(x.replace(",", ""))
    except ValueError:
        return None


def _money(a, ua, b=None, ub=None):
    ua = (ua or "").lower()
    ub = (ub or ua).lower()
    lo = _num(a)
    if lo is None or ua not in _UNIT:
        return None
    lo *= _UNIT[ua]
    hi = lo
    if b and ub in _UNIT and _num(b) is not None:
        hi = _num(b) * _UNIT[ub]
    return (min(lo, hi), max(lo, hi))


_AMT = r"\$\s?(\d[\d,\.]*)\s*(billion|million|thousand|bn|mm|m|b|k)\b(?:\s*(?:-|–|to|and)\s*\$\s?(\d[\d,\.]*)\s*(billion|million|thousand|bn|mm|m|b|k)?\b)?"


def relevant(snippet, company):
    toks = [t for t in re.sub(r"[^a-z0-9 ]", " ", company.lower()).split() if t not in _STOP and len(t) > 2]
    return bool(toks) and toks[0] in snippet.lower()


def parse_revenue(snips, company):
    """Return (low, high) in $ million from search snippets about THIS company, or None."""
    for sn in snips:
        if not relevant(sn, company):
            continue
        for pat in (rf"(?i)revenue[^$]{{0,70}}{_AMT}", rf"(?i){_AMT}\s*(?:in\s+)?(?:annual\s+)?revenue"):
            m = re.search(pat, sn)
            if m:
                r = _money(*m.groups())
                if r:
                    return r
    return None


def parse_employees(snips, company):
    for sn in snips:
        if not relevant(sn, company):
            continue
        m = re.search(r"(\d[\d,]*)\s*(?:-|–|to)\s*(\d[\d,]*)\s*(?:employees|staff|people)", sn, re.I)
        if m:
            a, b = _num(m.group(1)), _num(m.group(2))
            if a is not None and b is not None:
                return (min(a, b), max(a, b))
        m = re.search(r"(\d[\d,]*)\+?\s*employees", sn, re.I) or re.search(r"employees[^\d]{0,15}(\d[\d,]*)", sn, re.I)
        if m and _num(m.group(1)) is not None:
            v = _num(m.group(1))
            return (v, v)
    return None


def locations_count(text):
    m = re.search(r"\b(\d{1,3})\s+(?:locations|offices|branches|branch offices)\b", text, re.I)
    return int(m.group(1)) if m else 0


def big_signals(rec, text, nat, revenue, employees, big_names):
    """Independent signs that a company is too big. Revenue is one signal, never the only gate."""
    sig = []
    if revenue and revenue[0] > config.REVENUE_CEILING_M:            # whole range above the ceiling
        sig.append(f"revenue est ${revenue[0]:g}M+")
    if employees and employees[0] >= config.EMPLOYEES_BIG:
        sig.append(f"{int(employees[0])}+ employees")
    if locations_count(text) >= config.LOCATIONS_BIG:
        sig.append("4+ locations")
    if nat == "maybe":
        sig.append("national wording")
    if int(rec.get("multistate") or 1) >= config.MULTISTATE_BIG:
        sig.append("same name in other states")
    name = rec["company"].lower()
    if any(b and b in name for b in big_names):
        sig.append("on big-company list")
    return sig


# ---------------------------------------------------------------- v2: free extra source (Wayback Machine)
def wayback_pages(domain, max_pages=3):
    """Old copies of the company's home and contact pages (free). Returns list of HTML."""
    import requests
    out = []
    for path in ("", "/contact", "/contact-us", "/about"):
        if len(out) >= max_pages:
            break
        api = f"https://archive.org/wayback/available?url={domain}{path}"
        try:
            with _hit_lock:
                now = time.time()
                slot = max(now, _last_hit.get("archive.org", 0) + 1.0)
                _last_hit["archive.org"] = slot
            if slot > now:
                time.sleep(slot - now)
            j = requests.get(api, headers={"User-Agent": UA}, timeout=12).json()
            snap = j.get("archived_snapshots", {}).get("closest", {})
            if snap.get("available") and snap.get("url"):
                html = fetch(snap["url"].replace("http://", "https://"))
                if html:
                    out.append(html)
        except Exception:
            continue
    return out


# ---------------------------------------------------------------- v2.3: owner name and email patterns
def email_patterns(owner, domain):
    """Likely addresses for a known owner name. Only ever used if the mailbox is then VERIFIED."""
    parts = [re.sub(r"[^a-z]", "", p.lower()) for p in owner.split()]
    parts = [p for p in parts if p]
    if len(parts) < 2 or not domain:
        return []
    f, l = parts[0], parts[-1]
    pats = [f"{f}.{l}", f"{f}{l}", f"{f[0]}{l}", f, f"{f}_{l}", f"{f[0]}.{l}", f"{f}{l[0]}", l]
    out, seen = [], set()
    for p in pats:
        if p not in seen and len(p) > 1:
            seen.add(p)
            out.append(f"{p}@{domain}")
    return out


def owner_from_snippets(snips, company):
    """Owner or founder name from search result titles and snippets (LinkedIn titles, news, directories)."""
    for sn in snips:
        if not relevant(sn, company):
            continue
        name = extract_owner(sn)
        if name:
            return name
    return ""

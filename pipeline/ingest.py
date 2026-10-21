"""Step 1: turn a state license download (CSV or Excel) into clean rows."""
import csv
import io
import re

from . import config

MASTER_COLUMNS = ["key", "state", "license", "company", "owner", "address", "city", "zip",
                  "county", "phone", "classification", "status", "rank", "multistate"]


def _norm(h):
    return re.sub(r"[^a-z0-9 ]", " ", str(h or "").lower()).strip()


def _squash(h):
    return re.sub(r"\s+", " ", _norm(h))


def find_columns(headers):
    """Map our field names to the column index in this file. Exact match first, then 'contains'."""
    norm = [_squash(h) for h in headers]
    found = {}
    for field, aliases in config.COLUMN_ALIASES.items():
        idx = None
        for a in aliases:                      # exact
            if a in norm:
                idx = norm.index(a)
                break
        if idx is None:
            for a in aliases:                  # contains
                for i, h in enumerate(norm):
                    if h and a in h and i not in found.values():
                        idx = i
                        break
                if idx is not None:
                    break
        if idx is not None:
            found[field] = idx
    return found


def read_table(path):
    """Return a list of rows (lists of strings) from .csv or .xlsx."""
    p = str(path).lower()
    if p.endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        return [["" if c is None else str(c) for c in row] for row in ws.iter_rows(values_only=True)]
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8-sig", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",|\t;")
    except csv.Error:
        dialect = csv.excel
    return list(csv.reader(io.StringIO(text), dialect))


def find_header_row(rows):
    """Some downloads have title lines on top. Use the first row that looks like a header."""
    for i, row in enumerate(rows[:15]):
        cols = find_columns(row)
        if "company" in cols or ("license" in cols and "status" in cols):
            if len(cols) >= 3:
                return i, cols
    raise ValueError("Could not find a header row. Open the file and check the column names "
                     "against COLUMN_ALIASES in pipeline/config.py")


def clean_city(c):
    """'AUSTIN, TX 78701' -> 'Austin'  (some state files put city, state and zip in one column)"""
    c = str(c or "").strip()
    if "," in c:
        c = c.split(",")[0]
    c = re.sub(r"\s+[A-Z]{2}\s+\d{5}(-\d{4})?$", "", c)
    c = re.sub(r"\s+\d{5}(-\d{4})?$", "", c)
    return c.strip().title()


def clean_phone(p):
    d = re.sub(r"\D", "", str(p or ""))
    return d[-10:] if len(d) >= 10 else d


def flip_name(n):
    """'SMITH, JOHN A' -> 'John A Smith'"""
    n = str(n or "").strip()
    if "," in n:
        last, _, first = n.partition(",")
        n = f"{first.strip()} {last.strip()}"
    return n.title()


def is_active(status):
    s = str(status or "").lower()
    if not s:
        return True                     # file has no status column, keep and verify later
    if any(w in s for w in config.INACTIVE_WORDS):
        return False
    return any(w in s for w in config.ACTIVE_WORDS)


def company_key(state, license_no, company, city):
    lic = re.sub(r"[^A-Za-z0-9]", "", str(license_no or "")).upper()
    if lic:
        return f"{state}-{lic}"
    return f"{state}-{re.sub(r'[^a-z0-9]', '', (company + city).lower())}"


def rank_score(rec):
    """Cheap, free ranking of the raw pool BEFORE any research (higher = research first)."""
    n = rec["company"].lower()
    pts = 0
    if "solar" in n:
        pts += 4
    if any(w in n for w in ("energy", "power", "electric", "renew", "sun", "pv", "volt")):
        pts += 2
    if any(w in n for w in ("plumb", "hvac", "heating", "cooling", "paving", "concrete", "landscap", "pool", "fence", "tree")):
        pts -= 3
    if any(b in n for b in config.NATIONAL_BLOCKLIST):
        pts -= 10
    if re.search(r"\b(llc|inc|corp|co|ltd|incorporated|corporation)\b", n):
        pts += 1
    if len(rec.get("phone", "")) == 10:
        pts += 1
    if "46" in rec.get("classification", "") and "10" in rec.get("classification", ""):
        pts += 1                     # holds both solar and electrical: a real installer
    return pts


def load_licenses(path, state):
    state = state.upper()
    rows = read_table(path)
    hi, cols = find_header_row(rows)
    pattern = config.STATE_CLASS_FILTER.get(state)
    rx = re.compile(pattern, re.I) if pattern else None
    out, seen = [], set()

    def get(row, field):
        i = cols.get(field)
        return row[i].strip() if i is not None and i < len(row) and row[i] else ""

    for row in rows[hi + 1:]:
        if not any(row):
            continue
        company = get(row, "company") or get(row, "owner")
        if not company:
            continue
        class_ok = None
        if rx and "classification" in cols:
            class_ok = bool(rx.search(get(row, "classification")))
        name_hint = any(h in company.lower() for h in config.NAME_HINTS)
        if state in config.NAME_HINT_STATES:
            if not (class_ok or name_hint):
                continue
        elif class_ok is False:
            continue
        if not is_active(get(row, "status")):
            continue
        rec = {
            "state": state,
            "license": get(row, "license"),
            "company": company,
            "owner": flip_name(get(row, "owner")) if get(row, "owner").lower() != company.lower() else "",
            "address": get(row, "address"),
            "city": clean_city(get(row, "city")),
            "zip": get(row, "zip")[:5],
            "county": get(row, "county").title().replace(" County", ""),
            "phone": clean_phone(get(row, "phone")),
            "classification": get(row, "classification"),
            "status": get(row, "status"),
        }
        rec["key"] = company_key(state, rec["license"], company, rec["city"])
        rec["rank"] = rank_score(rec)
        rec["multistate"] = 1
        dup = rec["key"]
        if dup in seen:
            continue
        seen.add(dup)
        out.append(rec)
    return out

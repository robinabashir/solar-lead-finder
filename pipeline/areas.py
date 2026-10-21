"""Sample areas. Each day's companies are split across areas; a company only counts for an area
if there is written evidence that it serves that area."""
import csv
import re

from .web import counties_mentioned


def norm(s):
    """Compare places the same way on both sides: 'St. Petersburg', 'ST PETERSBURG' and 'Saint Petersburg' match."""
    s = re.sub(r"[.'’]", "", str(s or "").lower())
    s = re.sub(r"\bsaint\b", "st", s)
    s = re.sub(r"\bcounty\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


_COUNTY_ALIASES = {"miami-dade": "dade", "miami dade": "dade"}   # Florida files often say "Dade"


def load_areas(path="data/areas.csv"):
    """data/areas.csv columns: area_id, area_name, state, counties, cities, sample_ready
    counties and cities are separated by semicolons. sample_ready = yes/no."""
    areas = []
    try:
        with open(path, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if not r.get("area_id") or r["area_id"].startswith("#"):
                    continue
                areas.append({
                    "id": r["area_id"].strip(),
                    "name": r["area_name"].strip(),
                    "state": r["state"].strip().upper(),
                    "counties": set(),
                    "cities": {norm(c) for c in r["cities"].split(";") if c.strip()},
                    "ready": (r.get("sample_ready") or "yes").strip().lower() in ("yes", "y", "true", "1"),
                })
                for c in r["counties"].split(";"):
                    if c.strip():
                        areas[-1]["counties"].add(norm(c))
                        if norm(c) in _COUNTY_ALIASES:
                            areas[-1]["counties"].add(_COUNTY_ALIASES[norm(c)])
    except FileNotFoundError:
        pass
    return areas


def licensed_in_area(rec, area):
    """Evidence 1: the licensed business address is inside the area."""
    if rec["state"] != area["state"]:
        return False
    county = norm(rec.get("county"))
    if county and county in area["counties"]:
        return True
    return norm(rec.get("city")) in area["cities"]


def website_evidence(text, area):
    """Evidence 2: the website names an area county, or at least two area cities."""
    hit = {norm(c) for c in counties_mentioned(text)} & area["counties"]
    if hit:
        return "site names " + sorted(hit)[0].title() + " County"
    low = norm(text)
    cities = [c for c in area["cities"] if re.search(r"\b" + re.escape(c) + r"\b", low)]
    if len(cities) >= 2:
        return "site names " + ", ".join(sorted(c.title() for c in cities)[:3])
    return ""


def build_queues(master, areas, done):
    """Rank-ordered list of companies per area, from licensed addresses."""
    queues = {a["id"]: [] for a in areas}
    for rec in master:
        if rec["key"] in done:
            continue
        for a in areas:
            if licensed_in_area(rec, a):
                queues[a["id"]].append(rec)
    return queues


def pick_areas(areas, queues, k=3, forced=None):
    """Today's areas: forced list if given, else the ready areas with the most companies left,
    spreading across states first."""
    by_id = {a["id"]: a for a in areas}
    if forced:
        return [by_id[i] for i in forced if i in by_id][:k]
    ready = sorted([a for a in areas if a["ready"] and queues.get(a["id"])],
                   key=lambda a: -len(queues[a["id"]]))
    chosen, states = [], set()
    for a in ready:
        if a["state"] not in states and len(chosen) < k:
            chosen.append(a)
            states.add(a["state"])
    for a in ready:
        if a not in chosen and len(chosen) < k:
            chosen.append(a)
    return chosen

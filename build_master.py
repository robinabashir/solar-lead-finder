"""Build data/master.csv from the license downloads in data/raw/.
Name your files by state: data/raw/CA.xlsx, data/raw/FL.csv, data/raw/TX.csv ...
Run:  python build_master.py
"""
import csv
import glob
import os
import re

from pipeline import config
from pipeline.ingest import MASTER_COLUMNS, load_licenses


def main():
    files = sorted(glob.glob("data/raw/*"))
    allrows, seen_phone = [], set()
    for f in files:
        m = re.match(r"([A-Za-z]{2})", os.path.basename(f))
        if not m or not f.lower().endswith((".csv", ".xlsx", ".xlsm", ".txt")):
            continue
        state = m.group(1).upper()
        rows = load_licenses(f, state)
        print(f"{f}: {len(rows)} active solar-class companies")
        for r in rows:
            # same phone twice in a state = same company under two licenses
            pk = (state, r["phone"]) if len(r["phone"]) == 10 else None
            if pk and pk in seen_phone:
                continue
            if pk:
                seen_phone.add(pk)
            allrows.append(r)
    # same company name in several states = probably a national or regional chain
    def norm(n):
        return re.sub(r"\b(llc|inc|corp|co|ltd|company|incorporated)\b", "", re.sub(r"[^a-z0-9 ]", "", n.lower())).strip()
    states_by_name = {}
    for r in allrows:
        states_by_name.setdefault(norm(r["company"]), set()).add(r["state"])
    for r in allrows:
        r["multistate"] = len(states_by_name[norm(r["company"])])
    allrows.sort(key=lambda r: -r["rank"])
    counts = {}
    for r in allrows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    print("Companies per state:", counts)
    with open("data/master.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=MASTER_COLUMNS)
        w.writeheader()
        w.writerows(allrows)
    print(f"Wrote data/master.csv with {len(allrows)} companies")


if __name__ == "__main__":
    main()

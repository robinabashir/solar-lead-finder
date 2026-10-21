"""Preflight: run once before the real run. Prints PASS/FAIL for every part the system depends on."""
import glob
import os

from pipeline import areas as areamod
from pipeline import config, ingest, sheets
from pipeline.search import Searcher
from pipeline.verify import port25_ok


def line(ok, name, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("  -  " + detail if detail else ""))


def main():
    line(port25_ok(), "Outbound port 25 (mailbox checks)",
         "mailbox verification available" if port25_ok() else
         "blocked here: emails will be labelled published_only. Run this same script on your own computer to test there.")
    try:
        r = sheets.ping()
        line(bool(r.get("ok")), "Google Sheet web app + token", str(r))
    except Exception as e:
        line(False, "Google Sheet web app + token", str(e)[:100])
    s = Searcher(10)
    if not s.providers:
        line(False, "Search keys", "no SERPER_API_KEY / TAVILY_API_KEY / EXA_API_KEY found")
    for name, key in s.providers:
        try:
            res = s._call(name, key, "solar installer Tampa FL")
            line(len(res) > 0, f"Search: {name}", f"{len(res)} results")
        except Exception as e:
            line(False, f"Search: {name}", str(e)[:100])
    files = sorted(glob.glob("data/raw/*"))
    line(bool(files), "License files in data/raw", ", ".join(os.path.basename(f) for f in files) or "none yet")
    for f in files:
        st = os.path.basename(f)[:2].upper()
        try:
            n = len(ingest.load_licenses(f, st))
            line(n > 0, f"License file {os.path.basename(f)}", f"{n} companies kept")
        except Exception as e:
            line(False, f"License file {os.path.basename(f)}", str(e)[:120])
    a = areamod.load_areas()
    line(bool(a), "Sample areas (data/areas.csv)", f"{len(a)} areas")
    try:
        import run
        master = run.read_master()
        q = areamod.build_queues(master, a, set())
        for ar in a:
            print(f"      area {ar['id']:5} {ar['name']:22} {len(q[ar['id']]):5} licensed companies in area")
    except Exception as e:
        print("      (master.csv not built yet)", str(e)[:80])


if __name__ == "__main__":
    main()

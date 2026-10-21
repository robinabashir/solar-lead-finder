"""Checkpoint report. Paste bounced / replied / interested / paid emails in the Outcomes tab
(column A email, column B outcome), then run this to see what is working."""
from collections import defaultdict

from pipeline import sheets


def main():
    d = sheets.export()
    leads, outcomes = d.get("leads", []), {o["email"]: o["outcome"] for o in d.get("outcomes", [])}
    groups = {"Area": defaultdict(list), "Tier": defaultdict(list), "Email Status": defaultdict(list),
              "Email Source": defaultdict(list), "Label": defaultdict(list)}
    for r in leads:
        email = (r.get("Owner Email") or r.get("Company Email") or "").lower()
        out = outcomes.get(email, "")
        for k in groups:
            groups[k][r.get(k) or "-"].append(out)
    print(f"{len(leads)} leads, {len(outcomes)} outcomes recorded\n")
    for k, g in groups.items():
        print(f"By {k}:")
        for name, outs in sorted(g.items()):
            n = len(outs)
            rate = lambda w: f"{100 * sum(1 for o in outs if o in w) / n:.1f}%"
            print(f"  {name:22} sent {n:5}  bounced {rate(('bounced',)):>6}  replied {rate(('replied', 'interested', 'paid')):>6}"
                  f"  interested {rate(('interested', 'paid')):>6}  paid {rate(('paid',)):>6}")
        print()


if __name__ == "__main__":
    main()

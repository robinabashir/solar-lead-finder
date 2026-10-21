import os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from pipeline import areas, config, ingest, verify, web
import run

CSLB = """Title line from the download
License Number,Business Name,Address,City,State,ZIP,County,Phone,Classifications,Status
123456,BAY SOLAR INC,10 Main St,TAMPA,FL,33602,Hillsborough,(813) 555-0101,CVC,CLEAR
123457,PLUMB CO,1 Pipe Rd,TAMPA,FL,33603,Hillsborough,(813) 555-0102,CPC,CLEAR
123458,OLD SOLAR LLC,2 Sun Ave,TAMPA,FL,33604,Hillsborough,(813) 555-0103,CVC,EXPIRED
123459,SUNRUN INSTALLATION SERVICES,3 Big St,TAMPA,FL,33605,Hillsborough,(813) 555-0104,CVC,CLEAR
"""
HOME = """<html><body><a href="/contact-us">Contact</a><a href="/about">About Us</a>
<h1>Bay Solar</h1><p>Residential solar installation for homeowners in Hillsborough County. We install solar panels
and battery storage. Solar savings with free quote and financing. Lic# 123456. Call (813) 555-0101. Tampa, FL.</p></body></html>"""
CONTACT = """<html><body><p>Maria Lopez, Owner</p><a href="mailto:maria@baysolar.com">email</a>
<p>info [at] baysolar [dot] com</p><span data-cfemail="%s">[email protected]</span></body></html>"""
AREA = {"id": "TPA", "name": "Tampa Bay", "state": "FL", "counties": {"hillsborough", "pinellas"},
        "cities": {"tampa", "brandon", "clearwater"}, "ready": True}


def cf(email, key=0x42):
    return "%02x" % key + "".join("%02x" % (ord(c) ^ key) for c in email)


class NoSearch:
    used = 0
    cap = 100
    providers = []
    def left(self): return 0
    def search(self, q): return []
    def company_query(self, rec): return [], []
    def domain_emails(self, d): return []


class FakeVerifier:
    mode = "smtp"
    def __init__(self, status="verified"): self.s = status
    def status(self, e): return self.s


def shared(verifier=None, dir_index=None, big=None):
    return run.Shared(NoSearch(), verifier or FakeVerifier(), dir_index or {}, big or [], set(), set(), 0)


class T(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.f = os.path.join(d, "FL.csv")
        with open(self.f, "w") as fh: fh.write(CSLB)
        self.rec = ingest.load_licenses(self.f, "FL")[0]

    # ---- ingest
    def test_ingest(self):
        names = [r["company"] for r in ingest.load_licenses(self.f, "FL")]
        self.assertIn("BAY SOLAR INC", names)
        self.assertNotIn("PLUMB CO", names)
        self.assertNotIn("OLD SOLAR LLC", names)
        self.assertEqual(self.rec["phone"], "8135550101")
        self.assertGreater(self.rec["rank"], 5)
        self.assertEqual(ingest.flip_name("SMITH, JOHN A"), "John A Smith")

    def test_name_hint_states(self):
        d = tempfile.mkdtemp(); f = os.path.join(d, "TX.csv")
        open(f, "w").write("License Number,Business Name,City,State,County,Phone,Status\n"
                           "1,LONE STAR ELECTRIC LLC,Houston,TX,Harris,7135550101,Active\n"
                           "2,JOES PLUMBING,Houston,TX,Harris,7135550102,Active\n")
        self.assertEqual([r["company"] for r in ingest.load_licenses(f, "TX")], ["LONE STAR ELECTRIC LLC"])

    def test_tdlr_style_file(self):
        d = tempfile.mkdtemp(); f = os.path.join(d, "TX.csv")
        with open(f, "w") as fh:
            fh.write("LICENSE TYPE,LICENSE NUMBER,BUSINESS COUNTY,BUSINESS NAME,OWNER NAME,BUSINESS ADDRESS-LINE1,"
                     "\"BUSINESS CITY, STATE ZIP\",BUSINESS TELEPHONE\n"
                     "Electrical Contractor,12345,HARRIS,LONE STAR SOLAR LLC,\"DOE, JANE\",5 Main St,\"HOUSTON, TX 77002\",7135550101\n")
        r = ingest.load_licenses(f, "TX")
        self.assertEqual(len(r), 1)
        self.assertEqual((r[0]["city"], r[0]["county"], r[0]["owner"]), ("Houston", "Harris", "Jane Doe"))

    # ---- areas
    def test_areas(self):
        self.assertTrue(areas.licensed_in_area(self.rec, AREA))
        self.assertFalse(areas.licensed_in_area(dict(self.rec, county="Maricopa", city="Mesa"), AREA))
        self.assertIn("Pinellas", areas.website_evidence("We serve Pinellas County homeowners", AREA))
        self.assertIn("Tampa", areas.website_evidence("Serving Tampa and Brandon since 2010", AREA))
        self.assertEqual(areas.website_evidence("Serving Tampa only", AREA), "")
        stp = {"id": "TPA2", "name": "Tampa", "state": "FL", "counties": {"hillsborough"}, "cities": {"st petersburg"}, "ready": True}
        self.assertTrue(areas.licensed_in_area(dict(self.rec, county="", city="ST PETERSBURG"), stp))
        self.assertEqual(areas.norm("St. Petersburg"), areas.norm("Saint Petersburg"))
        import tempfile as _t
        _f = os.path.join(_t.mkdtemp(), "a.csv")
        with open(_f, "w") as fh:
            fh.write("area_id,area_name,state,counties,cities,sample_ready\nMIA,Miami,FL,Miami-Dade;Broward,Miami,yes\n")
        _a = areas.load_areas(_f)[0]
        self.assertIn("dade", _a["counties"])
        self.assertTrue(areas.licensed_in_area(dict(self.rec, county="DADE", city="x"), _a))
        q = areas.build_queues([self.rec], [AREA], set())
        self.assertEqual(len(q["TPA"]), 1)
        self.assertEqual(areas.build_queues([self.rec], [AREA], {self.rec["key"]})["TPA"], [])
        a2 = dict(AREA, id="PHX", state="AZ")
        picked = areas.pick_areas([AREA, a2], {"TPA": [1, 2], "PHX": [1]}, k=2)
        self.assertEqual({a["id"] for a in picked}, {"TPA", "PHX"})

    # ---- web helpers
    def test_emails_owner(self):
        html = CONTACT % cf("sales@baysolar.com")
        got = [e for e, _ in web.extract_emails(html)]
        for e in ("maria@baysolar.com", "info@baysolar.com", "sales@baysolar.com"):
            self.assertIn(e, got)
        self.assertEqual(web.extract_owner(web.text_of(html)), "Maria Lopez")
        o, c = web.classify_emails(web.extract_emails(html), "Maria Lopez", html, "baysolar.com")
        self.assertEqual(o, "maria@baysolar.com")

    def test_identity_national_screen(self):
        self.assertEqual(web.identity(web.text_of(HOME), self.rec)["level"], "strong")
        self.assertEqual(web.national_flag("Sunrun Installation Services", ""), "yes")
        self.assertEqual(web.national_flag("Local", "We install nationwide through franchise opportunities"), "yes")
        self.assertTrue(web.pure_installer(web.text_of(HOME))[0])
        self.assertFalse(web.pure_installer("We are a roofing company. One solar page.")[0])
        self.assertFalse(web.pure_installer("Commercial solar installation for businesses. solar solar install")[0])

    def test_size_parsing(self):
        c = "Bay Solar Inc"
        self.assertEqual(web.parse_revenue(["Bay Solar has annual revenue of $8.5 million and 45 employees"], c), (8.5, 8.5))
        self.assertEqual(web.parse_revenue(["Bay Solar - revenue between $10M and $25M"], c), (10.0, 25.0))
        self.assertIsNone(web.parse_revenue(["Other Co revenue $99 million"], c))
        self.assertEqual(web.parse_employees(["Bay Solar: 51-200 employees"], c), (51.0, 200.0))

    def test_big_signals(self):
        rec = dict(self.rec, multistate=1)
        s = web.big_signals(rec, "family owned", "no", (30.0, 50.0), (300.0, 500.0), [])
        self.assertEqual(len(s), 2)
        s = web.big_signals(rec, "family owned", "no", (10.0, 30.0), None, [])   # straddles: unknown
        self.assertEqual(s, [])
        s = web.big_signals(dict(rec, multistate=3), "We have 6 locations", "no", None, None, [])
        self.assertEqual(len(s), 2)

    # ---- verification
    def test_verifier(self):
        v = verify.Verifier("smtp")
        with mock.patch.object(verify, "mx_hosts", lambda d: ["mx.example.com"]):
            with mock.patch.object(verify, "probe", lambda h, a, timeout=10: [550] + [250] * (len(a) - 1)):
                self.assertEqual(v.status("a@strict.com"), "verified")
            v2 = verify.Verifier("smtp")
            with mock.patch.object(verify, "probe", lambda h, a, timeout=10: [250] * len(a)):
                self.assertEqual(v2.status("a@catchall.com"), "catch_all")
            v3 = verify.Verifier("smtp")
            with mock.patch.object(verify, "probe", lambda h, a, timeout=10: [550, 550]):
                self.assertEqual(v3.status("a@strict2.com"), "invalid")
            v4 = verify.Verifier("smtp")
            with mock.patch.object(verify, "probe", lambda h, a, timeout=10: None):
                self.assertEqual(v4.status("a@down.com"), "published_only")
        with mock.patch.object(verify, "mx_hosts", lambda d: ["x.mail.protection.outlook.com"]):
            self.assertEqual(verify.Verifier("smtp").status("a@m365.com"), "published_only")
        with mock.patch.object(verify, "mx_hosts", lambda d: []):
            self.assertEqual(verify.Verifier("mx").status("a@nomx.com"), "invalid")

    # ---- full company run
    def fake_fetch(self, url, *a, **k):
        if url.rstrip("/") == "https://baysolar.com":
            return HOME
        if "contact" in url:
            return CONTACT % cf("sales@baysolar.com")
        return None

    def run_proc(self, sh, rec=None):
        with mock.patch.object(web, "fetch", self.fake_fetch), mock.patch.object(web, "resolves", lambda d: d == "baysolar.com"), \
             mock.patch.object(web, "wayback_pages", lambda d: []):
            return run.process(rec or self.rec, AREA, sh)

    def test_process_green(self):
        row = self.run_proc(shared())
        self.assertEqual(row["Label"], "green")
        self.assertEqual(row["Owner Email"], "maria@baysolar.com")
        self.assertEqual(row["Email Status"], "verified")
        self.assertEqual(row["Area"], "Tampa Bay")
        self.assertIn("licensed address", row["Area Evidence"])

    def test_process_published_only_is_yellow(self):
        self.assertEqual(self.run_proc(shared(FakeVerifier("published_only")))["Label"], "yellow")

    def test_process_rejects(self):
        sh = shared(FakeVerifier("catch_all"))
        self.assertEqual(self.run_proc(sh)["Label"], "nomail")           # every email is catch-all
        sh = shared(big=["bay solar"])
        sh.seen_domains = set()
        # big-company list gives 1 signal only -> still passes as yellow
        row = self.run_proc(sh)
        self.assertEqual(row["Label"], "yellow")
        self.assertIn("big-company list", row["Size Signals"])
        sh2 = shared()
        sh2.seen_domains = {"baysolar.com"}
        self.assertEqual(self.run_proc(sh2)["Notes"], "domain already used")
        nat = dict(self.rec, company="SUNRUN INSTALLATION SERVICES")
        self.assertEqual(run.process(nat, AREA, shared())["Notes"], "national name")

    def test_directory_source(self):
        sh = shared(dir_index={"baysolar.com": ["owner@baysolar.com"]})
        def fetch_nomail(url, *a, **k):
            return HOME if url.rstrip("/") == "https://baysolar.com" else None
        with mock.patch.object(web, "fetch", fetch_nomail), mock.patch.object(web, "resolves", lambda d: d == "baysolar.com"), \
             mock.patch.object(web, "wayback_pages", lambda d: []):
            row = run.process(self.rec, AREA, sh)
        self.assertEqual(row["Email Source"], "directory")
        self.assertTrue(row["Company Email"] == "owner@baysolar.com" or row["Owner Email"] == "owner@baysolar.com")


if __name__ == "__main__":
    unittest.main(verbosity=2)

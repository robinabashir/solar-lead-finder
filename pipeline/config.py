"""Settings you can edit. Plain text, no secrets (secrets live in GitHub Secrets)."""
import os

TARGET_SENDABLE = int(os.getenv("TARGET_SENDABLE", "300"))    # stop after this many green+yellow rows
MAX_RUNTIME_MIN = int(os.getenv("MAX_RUNTIME_MIN", "100"))    # safety stop (GitHub free = 2,000 min/month)
SEARCH_DAILY_CAP = int(os.getenv("SEARCH_DAILY_CAP", "450"))  # searches per day, all providers together
REQUEST_DELAY_SEC = float(os.getenv("REQUEST_DELAY_SEC", "1.0"))
LIMIT_COMPANIES = int(os.getenv("LIMIT_COMPANIES", "0") or 0)  # test runs: stop after N companies (0 = no limit)
STATES = [s.strip().upper() for s in os.getenv("STATES", "CA,FL,TX,AZ").split(",") if s.strip()]

# Which license classes count as solar, per state (regex on the classification text).
# None = accept every row in the file. CHECK THESE against the real files on the test run.
STATE_CLASS_FILTER = {
    "CA": r"C-?46",
    "FL": r"solar|\bCVC\b|\bCV\b|\bRV\b",
    "AZ": r"solar|\b[CR]-?11\b",     # CHECK against the real ROC file
    "TX": None,                          # Texas has no solar license: electrical file + name hints
}
# States whose file has no solar class: keep only companies whose name hints at solar/energy/electric
NAME_HINT_STATES = {"TX", "AZ"}
NAME_HINTS = ("solar", "sun", "energy", "power", "electric", "pv", "renew", "green", "volt", "watt", "photovolt")

# License status words
ACTIVE_WORDS = ("active", "clear", "current", "valid")
INACTIVE_WORDS = ("inactive", "expired", "suspended", "revoked", "cancel", "delinquent", "null", "void")

# Column names we look for in license files (matched loosely, lower-case, no punctuation)
COLUMN_ALIASES = {
    "company": ["business name", "businessname", "dba name", "dba", "company", "firm name", "name of business"],
    "owner": ["licensee name", "licensee", "qualifier", "responsible managing officer", "rmo", "owner", "officer name"],
    "address": ["address", "address 1", "address1", "street", "mailing address", "business address"],
    "city": ["city"],
    "state": ["state"],
    "zip": ["zip", "zip code", "zipcode", "postal code"],
    "county": ["county", "county name"],
    "phone": ["phone", "business phone", "telephone", "phone number"],
    "license": ["license number", "license no", "license #", "licensenumber", "lic number", "license"],
    "status": ["license status", "primary status", "status"],
    "classification": ["classifications", "classification", "license class", "class code", "class", "license type", "services"],
    "email": ["email address", "email", "e mail"],
}
# Words that disqualify a column from matching a field by 'contains' (e.g. "License Verified/Deliver/Ship" is not the license number)
ALIAS_EXCLUDE = {"license": ("verified", "date", "expir", "status", "type", "class", "deliver", "ship")}

# Known national / big names (lower-case, matched inside the company name). Add your own.
NATIONAL_BLOCKLIST = [
    "sunrun", "tesla", "sunpower", "vivint", "sunnova", "palmetto", "freedom forever",
    "momentum solar", "blue raven", "adt solar", "trinity solar", "sunlight financial",
    "complete solar", "lumio", "titan solar", "grid alternatives", "sunbright", "pink energy",
    "powur", "sunworks", "solar insure", "enphase", "solaredge", "lg solar", "nrg",
]
# Phrases on a website that suggest a national / franchise company
NATIONAL_PHRASES = [
    "nationwide", "franchise opportunit", "own a franchise", "available in all 50 states",
    "across the united states", "coast to coast", "in over 20 states", "investor relations",
]

# Search results from these sites are never a company's own website
DIRECTORY_DOMAINS = {
    "yelp.com", "facebook.com", "instagram.com", "linkedin.com", "bbb.org", "yellowpages.com",
    "angi.com", "angieslist.com", "homeadvisor.com", "mapquest.com", "solarreviews.com",
    "energysage.com", "thumbtack.com", "youtube.com", "manta.com", "porch.com", "houzz.com",
    "twitter.com", "x.com", "nextdoor.com", "buzzfile.com", "dnb.com", "zoominfo.com",
    "opencorporates.com", "cslb.ca.gov", "myfloridalicense.com", "google.com", "bing.com",
    "tiktok.com", "pinterest.com", "glassdoor.com", "indeed.com", "chamberofcommerce.com",
    "birdeye.com", "trustpilot.com", "consumeraffairs.com", "wikipedia.org", "enfsolar.com",
    "solarpowerworldonline.com", "expertise.com", "bestcompany.com", "ratedpeople.com",
}

OWNER_TITLES = ["Owner", "Co-Owner", "Founder", "Co-Founder", "President", "CEO",
                "Chief Executive Officer", "Principal", "General Manager", "Sales Manager"]
ROLE_PREFIXES = ("info", "contact", "sales", "support", "admin", "office", "hello", "service",
                 "customerservice", "quotes", "estimates", "team", "help", "mail", "enquiries", "inquiries")


# ---------------------------------------------------------------- v2 settings
WORKERS = int(os.getenv("WORKERS", "8"))                       # companies processed at the same time
MANUAL_CAP = int(os.getenv("MANUAL_CAP", "15"))                # near-misses shown to you per day
VERIFY_MODE = os.getenv("VERIFY_MODE", "auto")                 # auto | smtp | mx
SMTP_FROM = os.getenv("SMTP_FROM", "check@example.org")
REVENUE_CEILING_M = float(os.getenv("REVENUE_CEILING_M", "20"))  # $ million: above this = big-company signal
MIN_REVENUE_M = float(os.getenv("MIN_REVENUE_M", "0"))           # 0 = no floor (your decision on small installers)
BIG_EXCLUDE_AT = int(os.getenv("BIG_EXCLUDE_AT", "2"))           # this many big signals = excluded
EMPLOYEES_BIG = int(os.getenv("EMPLOYEES_BIG", "100"))
LOCATIONS_BIG = int(os.getenv("LOCATIONS_BIG", "4"))
MULTISTATE_BIG = int(os.getenv("MULTISTATE_BIG", "2"))          # same company name in this many states of the pool

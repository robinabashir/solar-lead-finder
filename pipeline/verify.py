"""Email checks. Free, no paid verifier. Result per email:
  verified        mailbox accepted and the domain is NOT catch-all (needs outbound port 25)
  published_only  domain receives mail but a mailbox test is not possible (Microsoft 365, greylisting,
                  port 25 blocked): the email is only known from where we found it
  catch_all       domain accepts any address: rejected
  invalid         domain cannot receive mail, or the mailbox was refused: rejected"""
import random
import smtplib
import socket
import string
import threading

from . import config

_mx_cache = {}
_lock = threading.Lock()


def mx_hosts(domain):
    domain = domain.lower().strip()
    with _lock:
        if domain in _mx_cache:
            return _mx_cache[domain]
    hosts = []
    try:
        import dns.resolver
        try:
            ans = dns.resolver.resolve(domain, "MX", lifetime=6)
            hosts = [str(r.exchange).rstrip(".") for r in sorted(ans, key=lambda r: r.preference)]
        except Exception:
            try:
                dns.resolver.resolve(domain, "A", lifetime=6)
                hosts = [domain]                     # RFC fallback: mail goes to the A record
            except Exception:
                hosts = []
    except ImportError:
        try:
            socket.setdefaulttimeout(5)
            socket.gethostbyname(domain)
            hosts = [domain]
        except Exception:
            hosts = []
    with _lock:
        _mx_cache[domain] = hosts
    return hosts


def port25_ok(host="aspmx.l.google.com", timeout=8):
    try:
        s = socket.create_connection((host, 25), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def probe(host, addresses, timeout=10):
    """Ask the mail server RCPT TO for each address (nothing is sent). Returns list of SMTP codes or None."""
    try:
        with smtplib.SMTP(host, 25, timeout=timeout) as s:
            s.ehlo()
            s.mail(config.SMTP_FROM)
            codes = []
            for a in addresses:
                code, _ = s.rcpt(a)
                codes.append(code)
            return codes
    except Exception:
        return None


def _is_m365(hosts):
    return any(h.lower().endswith("protection.outlook.com") for h in hosts)


class Verifier:
    def __init__(self, mode=None):
        mode = (mode or config.VERIFY_MODE).lower()
        if mode == "auto":
            mode = "smtp" if port25_ok() else "mx"
        self.mode = mode
        self.domain_state = {}
        self.lock = threading.Lock()

    def status(self, email):
        local, _, dom = email.lower().partition("@")
        hosts = mx_hosts(dom)
        if not hosts:
            return "invalid"
        if self.mode != "smtp" or _is_m365(hosts):
            return "published_only"
        rnd = "zz" + "".join(random.choice(string.ascii_lowercase) for _ in range(12))
        with self.lock:
            known = self.domain_state.get(dom)
        if known is None:
            codes = probe(hosts[0], [f"{rnd}@{dom}", email])
            if codes is None:
                known = "unreachable"
            elif codes[0] == 250:
                known = "catch_all"
            elif 500 <= codes[0] < 600:
                known = "strict"
            else:
                known = "unreachable"
            with self.lock:
                self.domain_state[dom] = known
            if known == "strict" and codes:
                return self._code(codes[1])
        if known == "catch_all":
            return "catch_all"
        if known == "unreachable":
            return "published_only"
        codes = probe(hosts[0], [email])
        return self._code(codes[0]) if codes else "published_only"

    @staticmethod
    def _code(c):
        if c == 250:
            return "verified"
        if 500 <= c < 600:
            return "invalid"
        return "published_only"            # 4xx: temporary or greylisted

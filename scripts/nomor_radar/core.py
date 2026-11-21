# Copyright (c) 2026 EazyWhale (https://github.com/lonion-1/WhaleGuard)
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Inti bersama Radar Nomor v9: config TOML, HTTP tangguh + circuit breaker, kesehatan sumber, & state atomik."""
from __future__ import annotations

import html
import http.client
import json
import os
import random
import re
import socket
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
STATE_DIR = ROOT / ".github" / "nomor_state"
LEGACY_DISCOVERY = ROOT / ".github" / "discovered_channels.json"
LEGACY_SEEN = ROOT / ".github" / "nomor_radar_seen.json"
RULES_FILE = ROOT / "rules" / "numbers-spam-id.txt"
ALLOWLIST_FILE = ROOT / "rules" / "numbers-allowlist.txt"

DAY = 86400


def log(tag: str, msg: str) -> None:
    print(f"[{tag}] {msg}", flush=True)


def now() -> float:
    return time.time()


def day_of(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


DEFAULTS: dict = {
    "time_budget_seconds": 420,
    "finalize_reserve_seconds": 45,
    "polite_sleep": 1.0,
    "http_trip_after": 4,
    "promote_at": 3,
    "score_explicit_report": 3,
    "score_proximity_scam": 2,
    "score_page_context": 1,
    "max_new_numbers_per_run": 200,
    "max_promoted_per_source": 60,
    "pending_ttl_days": 21,
    "pending_max": 3000,
    "retire_hard_days": 4,
    "retire_soft_days": 14,
    "max_cooldown_hours": 72,
    "parole_days": 30,
    "reject_recheck_days": 30,
    "tg_channels_per_run": 25,
    "tg_max_channels": 80,
    "tg_max_pages": 4,
    "tg_max_dry_runs": 25,
    "tg_verify_per_run": 15,
    "tg_discovery_queries_per_run": 3,
    "tg_require_indonesian": True,
    "tg_queue_max": 400,
    "reddit_enabled": True,
    "reddit_queries_per_run": 3,
    "reddit_subreddits_per_run": 2,
    "reddit_posts_limit": 25,
    "reddit_comments_per_run": 10,
    "reddit_seen_max": 2500,
    "web_enabled": True,
    "web_pages_per_run": 18,
    "web_max_per_domain": 4,
    "web_max_queue": 500,
    "web_max_depth": 1,
    "web_fb_enabled": True,
    "web_fb_max_per_run": 5,
}


class ConfigError(Exception):
    pass


class Config:
    """Hasil muat semua file config/nomor_*.toml dengan regex terkompilasi."""

    T: dict
    warnings: list[str]


def _toml(name: str) -> dict:
    p = CONFIG_DIR / name
    try:
        with p.open("rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"config/{name} tidak ditemukan")
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"config/{name} salah format TOML: {e}")


def _compile(parts, label: str, prefix: str = "", suffix: str = "") -> re.Pattern:
    good = []
    for p in parts:
        p = str(p).strip()
        if not p:
            continue
        try:
            re.compile(p, re.I)
        except re.error as e:
            raise ConfigError(f"{label}: regex rusak {p!r} ({e})")
        good.append(f"(?:{p})")
    if not good:
        return re.compile(r"(?!x)x")
    try:
        return re.compile(f"{prefix}(?:{'|'.join(good)}){suffix}", re.I)
    except re.error as e:
        raise ConfigError(f"{label}: gabungan regex gagal ({e}); jangan pakai (?i)")


def load_config() -> Config:
    if tomllib is None:
        raise ConfigError("Butuh Python 3.11+ (modul tomllib).")

    kw = _toml("nomor_keywords.toml")
    seeds = _toml("nomor_seeds.toml")
    qs = _toml("nomor_queries.toml")
    sf = _toml("nomor_safety.toml")
    tn = _toml("nomor_tuning.toml")

    c = Config()
    c.warnings = []

    c.T = dict(DEFAULTS)
    for k, v in tn.items():
        if k not in DEFAULTS:
            c.warnings.append(f"nomor_tuning.toml: kunci tak dikenal '{k}' (typo?)")
            continue
        d = DEFAULTS[k]
        if isinstance(d, bool):
            if not isinstance(v, bool):
                raise ConfigError(f"nomor_tuning.toml: '{k}' harus true/false")
        elif not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ConfigError(f"nomor_tuning.toml: '{k}' harus angka")
        c.T[k] = v

    scam = kw.get("scam", {})
    noise = kw.get("noise", {})
    rel = kw.get("relevance", {})

    exp_list = list(scam.get("explicit_report_regex", []))
    prox_list = list(scam.get("proximity_regex", []))
    if not exp_list and not prox_list:
        raise ConfigError("nomor_keywords.toml: [scam] kosong — radar tidak punya pola deteksi")

    c.re_explicit = _compile(exp_list, "scam.explicit_report_regex", r"\b", r"\b")
    c.re_proximity = _compile(prox_list, "scam.proximity_regex")
    c.re_impersonation = _compile(
        scam.get("impersonation_override_regex", []), "scam.impersonation_override_regex", r"\b", r"\b"
    )
    c.re_official_cs = _compile(noise.get("official_cs_regex", []), "noise.official_cs_regex", r"\b", r"\b")
    c.re_commercial = _compile(noise.get("commercial_regex", []), "noise.commercial_regex", r"\b", r"\b")
    c.re_topic = _compile(rel.get("topic_regex", []), "relevance.topic_regex", r"\b", r"\b")
    c.re_indo = _compile(
        [re.escape(str(w).lower()) for w in rel.get("indonesian_hint", []) if str(w).strip()],
        "relevance.indonesian_hint",
        r"\b",
        r"\b",
    )

    c.dummy_numbers = {re.sub(r"\D", "", str(x)) for x in sf.get("dummy_numbers", []) if str(x).strip()}
    c.reserved_tg = {str(x).strip().lower() for x in sf.get("reserved_tg_names", []) if str(x).strip()}
    c.blocked_web_suffixes = tuple(str(x).strip().lower() for x in sf.get("blocked_web_suffixes", []) if str(x).strip())
    c.blocked_web_domains = {str(x).strip().lower().removeprefix("www.") for x in sf.get("blocked_web_domains", []) if str(x).strip()}

    c.seeds_tg = [str(x).strip().lstrip("@") for x in (seeds.get("telegram") or {}).get("channels", []) if str(x).strip()]
    c.seeds_reddit = [str(x).strip().removeprefix("r/") for x in (seeds.get("reddit") or {}).get("subreddits", []) if str(x).strip()]
    c.seeds_web = [str(x).strip() for x in (seeds.get("web") or {}).get("urls", []) if str(x).strip()]

    c.queries_tg = [str(x).strip() for x in (qs.get("telegram_discovery") or {}).get("queries", []) if str(x).strip()]
    c.queries_reddit = [str(x).strip() for x in (qs.get("reddit_search") or {}).get("queries", []) if str(x).strip()]

    return c


def norm_text(s: str) -> str:
    """NFKC: ubah angka/huruf fancy (𝟎𝟖𝟏𝟐 / 𝗣𝗘𝗡𝗜𝗣𝗨) menjadi ASCII standar."""
    return unicodedata.normalize("NFKC", s or "")


def bersihkan_html(raw: str) -> str:
    s = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", raw or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def host_of(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def is_facebook_url(url: str) -> bool:
    h = host_of(url)
    return h in {"facebook.com", "m.facebook.com", "mbasic.facebook.com", "web.facebook.com", "fb.com"} or h.endswith(".facebook.com")


def normalize_url(raw_url: str) -> str | None:
    u = html.unescape((raw_url or "").strip()).rstrip(').,;"\'<>]}')
    if not u:
        return None
    if u.startswith("//"):
        u = "https:" + u
    elif not re.match(r"^https?://", u, re.I):
        return None
    try:
        p = urllib.parse.urlparse(u)
    except Exception:
        return None
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    host = p.netloc.lower()
    if host in {"m.facebook.com", "mbasic.facebook.com", "web.facebook.com"}:
        host = "www.facebook.com"
    q_pairs = []
    for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=False):
        kl = k.lower()
        if kl.startswith("utm_") or kl in {"fbclid", "gclid", "ref", "refid", "source", "_rdc", "_rdr"}:
            continue
        q_pairs.append((k, v))
    clean_q = urllib.parse.urlencode(q_pairs)
    path = p.path or "/"
    return urllib.parse.urlunparse((p.scheme.lower(), host, path, "", clean_q, ""))


class Deadline:
    def __init__(self, seconds: float):
        self.end = time.monotonic() + max(0.0, seconds)

    def left(self) -> float:
        return self.end - time.monotonic()

    def expired(self, margin: float = 0.0) -> bool:
        return self.left() <= margin

    def sub(self, seconds: float) -> "Deadline":
        return Deadline(min(seconds, max(0.0, self.left())))


def polite(ctx: "Ctx", deadline: Deadline | None, base: float | None = None) -> None:
    base = ctx.cfg.T["polite_sleep"] if base is None else base
    wait = base + random.uniform(0, base * 0.5)
    if deadline is not None:
        wait = min(wait, max(0.0, deadline.left()))
    if wait > 0:
        time.sleep(wait)


UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]
_NX = {socket.EAI_NONAME, getattr(socket, "EAI_NODATA", -5)}


@dataclass
class Resp:
    status: int
    text: str | None
    url: str
    kind: str  # ok | gone | blocked | transient | skipped
    retry_after: float = 0.0

    @property
    def ok(self) -> bool:
        return self.kind == "ok"


class Http:
    def __init__(self, T: dict):
        self.T = T
        self.streak: dict[str, int] = {}
        self.tripped: set[str] = set()

    def is_tripped(self, host: str) -> bool:
        h = host.lower().removeprefix("www.")
        return h in self.tripped

    def _norm_host(self, url_or_host: str) -> str:
        h = urllib.parse.urlparse(url_or_host).netloc if "://" in url_or_host else url_or_host
        return h.lower().removeprefix("www.")

    def _success(self, host: str) -> None:
        self.streak[host] = 0

    def _failure(self, host: str) -> None:
        self.streak[host] = self.streak.get(host, 0) + 1
        if self.streak[host] >= self.T["http_trip_after"] and host not in self.tripped:
            self.tripped.add(host)
            log("BREAKER", f"{host} gagal {self.streak[host]}x berturut-turut → dilewati sisa run ini")

    def _once(self, url: str, timeout: float, max_bytes: int, extra_headers: dict[str, str] | None = None) -> Resp:
        headers = {
            "User-Agent": random.choice(UA_POOL),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read(max_bytes + 1)[:max_bytes]
                cs = r.headers.get_content_charset() or "utf-8"
                try:
                    text = raw.decode(cs, errors="ignore")
                except LookupError:
                    text = raw.decode("utf-8", errors="ignore")
                return Resp(getattr(r, "status", 200), text, r.geturl() or url, "ok")
        except urllib.error.HTTPError as e:
            st = e.code
            ra = 0.0
            try:
                ra = min(float(e.headers.get("Retry-After", "0")), 30.0)
            except (TypeError, ValueError):
                pass
            if st in (404, 410):
                kind = "gone"
            elif st >= 500 or st in (408, 425):
                kind = "transient"
            else:
                kind = "blocked"
            return Resp(st, None, url, kind, ra)
        except urllib.error.URLError as e:
            r = e.reason
            if isinstance(r, socket.gaierror) and r.errno in _NX:
                return Resp(0, None, url, "gone")
            return Resp(0, None, url, "transient")
        except (OSError, http.client.HTTPException):
            return Resp(0, None, url, "transient")
        except ValueError:
            return Resp(0, None, url, "gone")

    def get(
        self,
        url: str,
        *,
        timeout: float = 18,
        retries: int = 1,
        max_bytes: int = 2_000_000,
        deadline: Deadline | None = None,
        headers: dict[str, str] | None = None,
    ) -> Resp:
        host = self._norm_host(url)
        if host in self.tripped:
            return Resp(0, None, url, "skipped")
        last = Resp(0, None, url, "skipped")
        for attempt in range(retries + 1):
            if deadline is not None and deadline.left() < min(timeout, 5):
                return last
            resp = self._once(url, timeout, max_bytes, headers)
            if resp.kind == "ok":
                self._success(host)
                return resp
            if resp.kind == "gone":
                return resp
            last = resp
            if resp.kind == "blocked" and resp.status != 429:
                break
            if attempt < retries:
                wait = min(resp.retry_after or (2 ** attempt) * 1.5, 15) + random.uniform(0, 0.7)
                if deadline is not None and deadline.left() < wait + timeout:
                    break
                time.sleep(wait)
        self._failure(host)
        return last


class Store:
    """JSON state dengan tulis-atomik (.tmp -> os.replace) & pemulihan file korup."""

    def __init__(self, name: str, default: dict):
        self.path = STATE_DIR / f"{name}.json"
        self.data = json.loads(json.dumps(default))
        self.existed = False

    def load(self) -> "Store":
        if not self.path.exists():
            return self
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                raise ValueError("bukan objek JSON")
            self.data.update(d)
            self.existed = True
        except Exception as e:
            bad = self.path.with_name(self.path.name + ".bad")
            try:
                os.replace(self.path, bad)
            except OSError:
                pass
            log("STATE", f"{self.path.name} rusak ({e}) → dipindah ke {bad.name}, mulai bersih")
        return self

    def save(self, dry: bool = False) -> None:
        if dry:
            return
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)


def hl_ok(m: dict, ts: float) -> None:
    m.update(last_ok=int(ts), fails=0, cool_until=0, hard_days=[], soft_days=[])


def hl_fail(m: dict, kind: str, ts: float, T: dict) -> None:
    m["fails"] = int(m.get("fails", 0)) + 1
    key = "hard_days" if kind == "gone" else "soft_days"
    days = m.setdefault(key, [])
    d = day_of(ts)
    if d not in days:
        days.append(d)
        del days[:-30]
    hours = min(2 ** min(m["fails"], 8), T["max_cooldown_hours"])
    m["cool_until"] = int(ts + hours * 3600)


def hl_cooling(m: dict, ts: float) -> bool:
    return m.get("cool_until", 0) > ts


def hl_should_retire(m: dict, T: dict) -> bool:
    return len(m.get("hard_days", [])) >= T["retire_hard_days"] or len(m.get("soft_days", [])) >= T["retire_soft_days"]


@dataclass
class PhoneSighting:
    number: str
    source: str
    pts: int
    note: str = ""
    snippet: str = ""


@dataclass
class CollectorResult:
    name: str
    sightings: list[PhoneSighting] = field(default_factory=list)
    tg_candidates: list[tuple[str, str]] = field(default_factory=list)
    web_candidates: list[tuple[str, str, int]] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    error: str = ""


@dataclass
class Ctx:
    cfg: Config
    http: Http
    known_numbers: set[str]
    allowlist_numbers: set[str]
    ts: float
    dry: bool = False
  

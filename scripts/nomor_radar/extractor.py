# Copyright (c) 2026 EazyWhale (https://github.com/lonion-1/WhaleGuard)
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ekstraksi & penilaian nomor penipu Indonesia + penemuan tautan terbuka (Telegram, Web, Facebook)."""
from __future__ import annotations

import html
import re
import urllib.parse

from .core import (
    ALLOWLIST_FILE, RULES_FILE, Config, Ctx, PhoneSighting, is_facebook_url,
    norm_text, normalize_url,
)

RE_PHONE = re.compile(
    r"(?<![\d+])(?:\(?\+?62\)?|0)[ .\-]?8[1-9]\d(?:[ .\-]?\d){5,9}(?!\d)"
)
RE_WA_LINK = re.compile(
    r"""(?:wa\.me/|api\.whatsapp\.com/send\?[^\s"'<>]*?phone=)\+?((?:62|0)8[1-9]\d{7,10})""",
    re.I,
)
RE_EXISTING_RULE = re.compile(r"^\^?\(\\?\+62\|62\|0\)([2-9]\d{7,11})\$?$")

RE_TG_MENTION = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?([a-zA-Z][a-zA-Z0-9_]{4,31})\b",
    re.I,
)
RE_RAW_URL = re.compile(r"""https?://[^\s"'<>()\[\]]+""", re.I)


def normalisasi_nomor(cfg: Config, raw: str) -> str | None:
    d = re.sub(r"\D", "", norm_text(raw))
    if d.startswith("62"):
        d = "0" + d[2:]
    if not re.fullmatch(r"08[1-9]\d{7,10}", d):
        return None
    if d in cfg.dummy_numbers:
        return None
    tail = d[2:]
    if len(set(tail)) <= 1:
        return None
    if tail in "01234567890123456789" or tail in "98765432109876543210":
        return None
    return d


def nomor_ke_regex(norm_08: str) -> str:
    return rf"^(\+62|62|0){norm_08[1:]}$"


def muat_daftar_nomor(cfg: Config, path) -> set[str]:
    hasil: set[str] = set()
    if not path.exists():
        return hasil
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.split("#", 1)[0].strip()
        if not s or s.startswith("!"):
            continue
        m = RE_EXISTING_RULE.match(s)
        if m:
            hasil.add("0" + m.group(1))
        else:
            norm = normalisasi_nomor(cfg, s)
            if norm:
                hasil.add(norm)
    return hasil


def load_known_numbers(ctx: Ctx) -> None:
    ctx.known_numbers.update(muat_daftar_nomor(ctx.cfg, RULES_FILE))
    ctx.allowlist_numbers.update(muat_daftar_nomor(ctx.cfg, ALLOWLIST_FILE))


def extract_tg_usernames(cfg: Config, text: str) -> set[str]:
    out: set[str] = set()
    for m in RE_TG_MENTION.finditer(norm_text(text)):
        u = m.group(1)
        low = u.lower()
        if low in cfg.reserved_tg or low.endswith("bot"):
            continue
        out.add(u)
    return out


def is_crawlable_web_url(cfg: Config, url: str) -> bool:
    u = normalize_url(url)
    if not u:
        return False
    p = urllib.parse.urlparse(u)
    h = p.netloc.lower().removeprefix("www.")
    if not h or "." not in h:
        return False
    if h.endswith(cfg.blocked_web_suffixes):
        return False
    if h in cfg.blocked_web_domains or any(h.endswith("." + b) for b in cfg.blocked_web_domains):
        return False
    if re.search(r"\.(?:jpg|jpeg|png|gif|webp|svg|mp4|mp3|pdf|zip|rar|apk|exe|css|js)$", p.path, re.I):
        return False
    if is_facebook_url(u):
        if not cfg.T.get("web_fb_enabled", True):
            return False
        path_l = p.path.lower()
        if path_l in ("", "/") or any(x in path_l for x in ("/login", "/checkpoint", "/watch", "/reel", "/marketplace", "/policies")):
            return False
    return True


def extract_outbound_links(cfg: Config, text: str, hrefs: list[str] | None = None) -> tuple[set[str], set[str]]:
    blob = norm_text(text) + " " + " ".join(html.unescape(h) for h in (hrefs or []))
    tgs = extract_tg_usernames(cfg, blob)
    webs: set[str] = set()
    for m in RE_RAW_URL.finditer(blob):
        norm = normalize_url(m.group(0))
        if norm and is_crawlable_web_url(cfg, norm):
            webs.add(norm)
    return tgs, webs


def score_number_in_context(
    cfg: Config,
    text: str,
    start: int,
    end: int,
    *,
    has_page_context: bool = False,
) -> tuple[int, str]:
    T = cfg.T
    win_tight = text[max(0, start - 55):min(len(text), end + 55)]
    win_wide = text[max(0, start - 95):min(len(text), end + 95)]

    if cfg.re_official_cs.search(win_tight) and not cfg.re_impersonation.search(win_wide):
        return 0, ""

    if cfg.re_explicit.search(win_wide):
        return T["score_explicit_report"], "explicit_report"

    if cfg.re_proximity.search(win_wide):
        return T["score_proximity_scam"], "proximity_scam"

    if has_page_context:
        return T["score_page_context"], "page_context"

    return 0, ""


def extract_phone_sightings(
    ctx: Ctx,
    text: str,
    source: str,
    *,
    has_page_context: bool = False,
) -> list[PhoneSighting]:
    cfg = ctx.cfg
    clean = norm_text(text)
    if not clean:
        return []

    if cfg.re_commercial.search(clean) and not cfg.re_explicit.search(clean):
        return []

    ignore = ctx.known_numbers | ctx.allowlist_numbers
    best: dict[str, PhoneSighting] = {}

    matches: list[tuple[str, int, int]] = [(m.group(0), m.start(), m.end()) for m in RE_PHONE.finditer(clean)]
    for m in RE_WA_LINK.finditer(clean):
        matches.append((m.group(1), m.start(), m.end()))

    for raw_num, st, en in matches:
        norm = normalisasi_nomor(cfg, raw_num)
        if not norm or norm in ignore:
            continue
        pts, note = score_number_in_context(cfg, clean, st, en, has_page_context=has_page_context)
        if pts <= 0:
            continue
        snippet = clean[max(0, st - 35):min(len(clean), en + 35)].strip()
        if norm not in best or pts > best[norm].pts:
            best[norm] = PhoneSighting(norm, source, pts, note, snippet)

    return list(best.values())
  

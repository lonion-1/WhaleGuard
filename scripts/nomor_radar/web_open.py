# Copyright (c) 2026 EazyWhale (https://github.com/lonion-1/WhaleGuard)
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Collector Open Web, Forum & Facebook Publik: merayapi tautan terbuka hasil snowball & seed."""
from __future__ import annotations

import html
import re
import urllib.parse

from .core import (
    DAY, CollectorResult, Ctx, Deadline, bersihkan_html, host_of, is_facebook_url,
    log, norm_text, normalize_url, polite,
)
from .extractor import (
    extract_outbound_links, extract_phone_sightings, is_crawlable_web_url,
)

DEFAULT_STATE = {
    "version": 9,
    "queue": {},
    "visited": {},
    "rejected": {},
}

RE_HREF = re.compile(r"""href=["']([^"'#]+)["']""", re.I)
RE_META_DESC = re.compile(
    r"""<meta[^>]+(?:property|name)=["'](?:og:title|og:description|description|twitter:description)["'][^>]+content=["']([^"']+)["']""",
    re.I,
)
RE_TITLE_TAG = re.compile(r"<title[^>]*>([\s\S]*?)</title>", re.I)
RE_FB_LOGIN_WALL = re.compile(
    r"(?:login\.php|/login/|/checkpoint/|log\s+in\s+to\s+facebook|masuk\s+ke\s+facebook|you\s+must\s+log\s+in\s+to\s+continue)",
    re.I,
)


def _extract_meta_preview(raw_html: str) -> str:
    parts: list[str] = []
    tm = RE_TITLE_TAG.search(raw_html or "")
    if tm:
        parts.append(bersihkan_html(tm.group(1)))
    for m in RE_META_DESC.finditer(raw_html or ""):
        parts.append(html.unescape(m.group(1)))
    return norm_text(" ".join(p for p in parts if p))


def _enqueue(ctx: Ctx, st: dict, url: str, src: str, depth: int) -> None:
    cfg, T = ctx.cfg, ctx.cfg.T
    if depth > T["web_max_depth"] and src != "seed":
        return
    norm = normalize_url(url)
    if not norm or not is_crawlable_web_url(cfg, norm):
        return
    if norm in st["queue"] or norm in st["visited"] or norm in st["rejected"]:
        return
    st["queue"][norm] = {"src": src, "depth": depth, "ts": int(ctx.ts), "tries": 0}


def _housekeeping(ctx: Ctx, st: dict) -> None:
    T, ts = ctx.cfg.T, ctx.ts
    cut = ts - T["reject_recheck_days"] * DAY
    st["visited"] = {u: t for u, t in st["visited"].items() if t > cut}
    st["rejected"] = {u: t for u, t in st["rejected"].items() if t > cut}
    if len(st["queue"]) > T["web_max_queue"]:
        keep = sorted(st["queue"].items(), key=lambda kv: (kv[1].get("depth", 1), -kv[1].get("ts", 0)))[:T["web_max_queue"]]
        st["queue"] = dict(keep)


def run(ctx: Ctx, st: dict, deadline: Deadline, incoming_web: list[tuple[str, str, int]]) -> CollectorResult:
    cfg, T, ts = ctx.cfg, ctx.cfg.T, ctx.ts
    stats: dict = {"scanned": 0, "fb_tried": 0, "fb_walled": 0, "found": 0, "queued": 0}
    if not T.get("web_enabled", True):
        return CollectorResult("web", stats=stats)

    sightings = []
    tg_out: list[tuple[str, str]] = []

    _housekeeping(ctx, st)

    for u in cfg.seeds_web:
        _enqueue(ctx, st, u, "seed", 0)
    for u, src, depth in incoming_web:
        _enqueue(ctx, st, u, src, depth)

    order = sorted(st["queue"].items(), key=lambda kv: (kv[1].get("depth", 1), kv[1].get("ts", 0)))
    domain_counts: dict[str, int] = {}
    scanned = 0
    fb_tried = 0

    for url, meta in order:
        if scanned >= T["web_pages_per_run"] or deadline.expired(8):
            break

        h = host_of(url)
        is_fb = is_facebook_url(url)
        if is_fb:
            if not T.get("web_fb_enabled", True) or fb_tried >= T["web_fb_max_per_run"]:
                continue
            if ctx.http.is_tripped("facebook.com"):
                continue
        else:
            if ctx.http.is_tripped(h):
                continue
            if domain_counts.get(h, 0) >= T["web_max_per_domain"]:
                continue

        r = ctx.http.get(url, timeout=16, retries=0, max_bytes=1_500_000, deadline=deadline)
        if r.kind == "skipped":
            continue

        if is_fb:
            fb_tried += 1
            stats["fb_tried"] = fb_tried

        if not r.ok:
            if r.kind == "gone":
                st["queue"].pop(url, None)
                st["rejected"][url] = int(ts)
            elif r.kind == "blocked":
                st["queue"].pop(url, None)
                st["rejected"][url] = int(ts)
                if is_fb:
                    stats["fb_walled"] += 1
            else:
                meta["tries"] = meta.get("tries", 0) + 1
                if meta["tries"] >= 3:
                    st["queue"].pop(url, None)
                    st["rejected"][url] = int(ts)
            polite(ctx, deadline, 1.0)
            continue

        raw = r.text or ""
        st["queue"].pop(url, None)
        scanned += 1
        domain_counts[h] = domain_counts.get(h, 0) + 1

        meta_preview = _extract_meta_preview(raw)
        body_text = bersihkan_html(raw)

        if is_fb and (RE_FB_LOGIN_WALL.search(r.url) or RE_FB_LOGIN_WALL.search(raw[:40_000])):
            stats["fb_walled"] += 1
            st["rejected"][url] = int(ts)
            if meta_preview and cfg.re_topic.search(meta_preview) and len(cfg.re_indo.findall(meta_preview)) >= 2:
                s_list = extract_phone_sightings(ctx, meta_preview, "web:facebook.com(meta)", has_page_context=True)
                sightings.extend(s_list)
                stats["found"] += len(s_list)
                tgs, _ = extract_outbound_links(cfg, meta_preview)
                for u in tgs:
                    tg_out.append((u, "web:facebook.com"))
            polite(ctx, deadline, 1.2)
            continue

        combined_text = norm_text(f"{meta_preview}\n{body_text}")
        is_relevant = bool(cfg.re_topic.search(combined_text))
        is_indo = len(cfg.re_indo.findall(combined_text)) >= 3

        if not (is_relevant and is_indo):
            st["rejected"][url] = int(ts)
            polite(ctx, deadline, 0.8)
            continue

        st["visited"][url] = int(ts)
        src_tag = f"web:{h}"
        s_list = extract_phone_sightings(ctx, combined_text, src_tag, has_page_context=True)
        sightings.extend(s_list)
        stats["found"] += len(s_list)

        abs_hrefs = [urllib.parse.urljoin(r.url or url, html.unescape(href)) for href in RE_HREF.findall(raw)]
        tgs, webs = extract_outbound_links(cfg, combined_text, abs_hrefs)
        for u in tgs:
            tg_out.append((u, src_tag))
        next_depth = int(meta.get("depth", 1)) + 1
        if next_depth <= T["web_max_depth"]:
            for w in webs:
                if host_of(w) == h and cfg.re_topic.search(w):
                    _enqueue(ctx, st, w, src_tag, next_depth)

        polite(ctx, deadline, 1.0)

    stats["scanned"] = scanned
    stats["queued"] = len(st["queue"])
    log(
        "WEB",
        f"{scanned} halaman dipindai (FB dicoba={fb_tried}, walled={stats['fb_walled']}), "
        f"+{stats['found']} nomor, antrean={stats['queued']}",
    )
    return CollectorResult("web", sightings, tg_out, [], stats)
      

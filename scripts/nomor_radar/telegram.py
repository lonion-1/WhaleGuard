# Copyright (c) 2026 EazyWhale (https://github.com/lonion-1/WhaleGuard)
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Collector Telegram: pantau kanal publik (t.me/s/...) dengan kursor last_post, snowball & direktori."""
from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass

from .core import (
    DAY, CollectorResult, Ctx, Deadline, bersihkan_html, hl_cooling, hl_fail, hl_ok,
    hl_should_retire, log, norm_text, polite,
)
from .extractor import extract_outbound_links, extract_phone_sightings, extract_tg_usernames

RE_POST_MARK = re.compile(r'data-post="([^"]+)"')
RE_TG_TEXT = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>([\s\S]*?)</div>')
RE_HREF = re.compile(r"""href=["'](https?://[^"']+)["']""", re.I)
RE_TITLE = re.compile(r'class="tgme_channel_info_header_title"[^>]*>([\s\S]*?)</div>')
RE_DESC = re.compile(r'class="tgme_channel_info_description"[^>]*>([\s\S]*?)</div>')

DEFAULT_STATE = {
    "version": 9,
    "channels": {},
    "retired": {},
    "rejected": {},
    "queue": {},
    "disc_cursor": 0,
}


@dataclass
class Post:
    pid: str
    num: int
    text: str
    hrefs: list[str]


def new_meta(source: str) -> dict:
    return {
        "source": source,
        "scans": 0,
        "harvested": 0,
        "dry_runs": 0,
        "last_scan": 0,
        "last_post": 0,
    }


def parse_posts(raw: str) -> list[Post]:
    marks = list(RE_POST_MARK.finditer(raw))
    merged: dict[str, Post] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(raw)
        block = raw[m.start():end]
        pid = m.group(1)
        tail = pid.rsplit("/", 1)[-1]
        text = " ".join(t for t in (bersihkan_html(x) for x in RE_TG_TEXT.findall(block)) if t)
        hrefs = [html.unescape(h) for h in RE_HREF.findall(block)]
        if pid in merged:
            merged[pid].text = (merged[pid].text + " " + text).strip()
            merged[pid].hrefs.extend(hrefs)
        else:
            merged[pid] = Post(pid, int(tail) if tail.isdigit() else 0, text, hrefs)
    return sorted(merged.values(), key=lambda p: p.num)


def fetch_channel(ctx: Ctx, name: str, last_post: int, deadline: Deadline) -> tuple[str, list[Post]]:
    T = ctx.cfg.T
    got: dict[str, Post] = {}
    before: int | None = None

    for page in range(T["tg_max_pages"]):
        url = f"https://t.me/s/{name}" + (f"?before={before}" if before else "")
        r = ctx.http.get(url, timeout=18, retries=1, deadline=deadline)
        if not r.ok:
            if page == 0:
                return r.kind, []
            break
        if "tgme_widget_message" not in (r.text or ""):
            if page == 0:
                return "gone", []
            break
        posts = parse_posts(r.text or "")
        if not posts:
            break
        for p in posts:
            got[p.pid] = p
        nums = [p.num for p in posts if p.num > 0]
        if not nums:
            break
        oldest = min(nums)
        if oldest <= last_post or oldest <= 1 or oldest == before:
            break
        before = oldest
        polite(ctx, deadline, 0.8)

    fresh = [p for p in got.values() if p.num > last_post] if last_post else list(got.values())
    return "ok", sorted(fresh, key=lambda p: p.num)


def verify_channel(ctx: Ctx, name: str, deadline: Deadline) -> str:
    cfg, T = ctx.cfg, ctx.cfg.T
    r = ctx.http.get(f"https://t.me/s/{name}", timeout=18, retries=1, deadline=deadline)
    if r.kind == "skipped":
        return "retry"
    if not r.ok:
        return "reject" if r.kind == "gone" else "retry"
    if "tgme_widget_message_text" not in (r.text or ""):
        return "reject"

    posts = [p for p in parse_posts(r.text or "") if p.text]
    if len(posts) < 2:
        return "reject"

    t_m = RE_TITLE.search(r.text or "")
    d_m = RE_DESC.search(r.text or "")
    sample = norm_text(" ".join([
        bersihkan_html(t_m.group(1)) if t_m else "",
        bersihkan_html(d_m.group(1)) if d_m else "",
        *[p.text for p in posts[-10:]],
    ]))

    if T["tg_require_indonesian"] and len(cfg.re_indo.findall(sample)) < 3:
        return "reject"
    if cfg.re_topic.search(sample):
        return "accept"
    return "reject"


def _housekeeping(st: dict, ts: float, T: dict) -> None:
    st["retired"] = {k: v for k, v in st["retired"].items() if v > ts}
    cut = ts - T["reject_recheck_days"] * DAY
    st["rejected"] = {k: v for k, v in st["rejected"].items() if v > cut}
    if len(st["rejected"]) > 3000:
        keep = sorted(st["rejected"].items(), key=lambda kv: kv[1], reverse=True)[:3000]
        st["rejected"] = dict(keep)
    if len(st["queue"]) > T["tg_queue_max"]:
        keep = sorted(st["queue"].items(), key=lambda kv: kv[1].get("ts", 0), reverse=True)[:T["tg_queue_max"]]
        st["queue"] = dict(keep)


def _sync_seeds(ctx: Ctx, st: dict) -> None:
    cfg, ts = ctx.cfg, ctx.ts
    ch = st["channels"]
    seeds_lc = {k.lower(): k for k in cfg.seeds_tg}
    for name in [n for n, m in ch.items() if m.get("source") == "seed" and n.lower() not in seeds_lc]:
        log("SEED", f"@{name} dihapus dari nomor_seeds.toml → dikeluarkan")
        ch.pop(name, None)
    have = {n.lower() for n in ch}
    for lc, name in seeds_lc.items():
        if lc not in have and st["retired"].get(lc, 0) <= ts:
            ch[name] = new_meta("seed")


def _enqueue(ctx: Ctx, st: dict, name: str, src: str) -> None:
    lc = name.lower()
    if (
        lc in {n.lower() for n in st["channels"]}
        or lc in st["rejected"]
        or st["retired"].get(lc, 0) > ctx.ts
        or lc in st["queue"]
    ):
        return
    st["queue"][lc] = {"name": name, "src": src, "ts": int(ctx.ts), "tries": 0}


def _discover(ctx: Ctx, st: dict, deadline: Deadline, stats: dict) -> None:
    cfg, T = ctx.cfg, ctx.cfg.T
    urls = [f"https://lyzem.com/search?q={urllib.parse.quote_plus(q)}" for q in cfg.queries_tg]
    if not urls:
        return
    cur = int(st.get("disc_cursor", 0)) % len(urls)
    n = min(T["tg_discovery_queries_per_run"], len(urls))
    for i in range(n):
        if deadline.expired(5):
            break
        r = ctx.http.get(urls[(cur + i) % len(urls)], timeout=18, retries=1, deadline=deadline)
        if r.ok:
            st["disc_cursor"] = (cur + i + 1) % len(urls)
            for u in extract_tg_usernames(cfg, r.text or ""):
                _enqueue(ctx, st, u, "directory")
        elif ctx.http.is_tripped("lyzem.com"):
            break
        polite(ctx, deadline, 1.0)
    stats["queue"] = len(st["queue"])


def _verify_queue(ctx: Ctx, st: dict, deadline: Deadline, stats: dict) -> None:
    T = ctx.cfg.T
    order = sorted(st["queue"].items(), key=lambda kv: kv[1].get("ts", 0))
    done = 0
    for lc, q in order:
        if done >= T["tg_verify_per_run"] or deadline.expired(5):
            break
        if len(st["channels"]) >= T["tg_max_channels"]:
            break
        verdict = verify_channel(ctx, q["name"], deadline)
        if verdict == "retry":
            q["tries"] = q.get("tries", 0) + 1
            if q["tries"] >= 4:
                st["rejected"][lc] = int(ctx.ts)
                st["queue"].pop(lc, None)
            if ctx.http.is_tripped("t.me"):
                break
            continue
        done += 1
        st["queue"].pop(lc, None)
        if verdict == "accept":
            st["channels"][q["name"]] = new_meta(q["src"])
            stats["new_channels"] = stats.get("new_channels", 0) + 1
            log("NEW-TG", f"@{q['name']} ({q['src']})")
        else:
            st["rejected"][lc] = int(ctx.ts)
        polite(ctx, deadline, 0.9)


def run(ctx: Ctx, st: dict, deadline: Deadline, incoming_tg: list[tuple[str, str]]) -> CollectorResult:
    cfg, T, ts = ctx.cfg, ctx.cfg.T, ctx.ts
    stats: dict = {"scanned": 0, "posts": 0, "found": 0, "failed": 0}
    sightings = []
    tg_out: list[tuple[str, str]] = []
    web_out: list[tuple[str, str, int]] = []

    _housekeeping(st, ts, T)
    _sync_seeds(ctx, st)

    for uname, src in incoming_tg:
        _enqueue(ctx, st, uname, src)

    _discover(ctx, st, deadline.sub(deadline.left() * 0.2), stats)

    ch = st["channels"]
    order = sorted((m.get("last_scan", 0), n) for n, m in ch.items() if not hl_cooling(m, ts))
    to_retire: list[tuple[str, str]] = []
    scan_dl = deadline.sub(deadline.left() * 0.78)

    for _, name in order[:T["tg_channels_per_run"]]:
        if scan_dl.expired(8):
            stats["time_up"] = 1
            break
        m = ch[name]
        status, posts = fetch_channel(ctx, name, m.get("last_post", 0), scan_dl)
        if status == "skipped":
            if ctx.http.is_tripped("t.me"):
                break
            continue
        m["last_scan"] = int(ts)
        m["scans"] = m.get("scans", 0) + 1
        if status != "ok":
            hl_fail(m, status, ts, T)
            stats["failed"] += 1
            if m.get("source") != "seed" and hl_should_retire(m, T):
                to_retire.append((name, "gagal diakses berulang"))
            polite(ctx, scan_dl, 0.8)
            continue

        hl_ok(m, ts)
        found = 0
        for p in posts:
            s_list = extract_phone_sightings(ctx, p.text, f"tg:@{name}", has_page_context=True)
            sightings.extend(s_list)
            found += len(s_list)

            if cfg.re_topic.search(p.text):
                tgs, webs = extract_outbound_links(cfg, p.text, p.hrefs)
                for u in tgs:
                    _enqueue(ctx, st, u, f"snowball:@{name}")
                    tg_out.append((u, f"tg:@{name}"))
                for w in webs:
                    web_out.append((w, f"tg:@{name}", 1))

        if posts:
            m["last_post"] = max(m.get("last_post", 0), max(p.num for p in posts))
            if found > 0:
                m["harvested"] = m.get("harvested", 0) + found
                m["dry_runs"] = 0
            else:
                m["dry_runs"] = m.get("dry_runs", 0) + 1
                if m.get("source") != "seed" and m["dry_runs"] >= T["tg_max_dry_runs"]:
                    to_retire.append((name, f"zonk {T['tg_max_dry_runs']}x pada post baru"))

        stats["scanned"] += 1
        stats["posts"] += len(posts)
        stats["found"] += found
        log("TG", f"@{name} ({m.get('source')}): {len(posts)} post baru, +{found} nomor")
        polite(ctx, scan_dl, 0.8)

    for name, why in to_retire:
        log("PAROLE", f"@{name} dipensiunkan ({why}); dicoba lagi setelah {T['parole_days']} hari")
        ch.pop(name, None)
        st["retired"][name.lower()] = int(ts + T["parole_days"] * DAY)

    _verify_queue(ctx, st, deadline, stats)
    stats["channels"] = len(ch)
    return CollectorResult("telegram", sightings, tg_out, web_out, stats)
  

# Copyright (c) 2026 EazyWhale (https://github.com/lonion-1/WhaleGuard)
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Collector Reddit Publik: pindai thread & komentar diskusi pinjol/galbay/penipu di Reddit."""
from __future__ import annotations

import json
import urllib.parse

from .core import CollectorResult, Ctx, Deadline, log, norm_text, polite
from .extractor import extract_outbound_links, extract_phone_sightings

DEFAULT_STATE = {
    "version": 9,
    "seen_posts": {},
    "query_cursor": 0,
    "sub_cursor": 0,
}

REDDIT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; WhaleGuard-OSINT-Radar/9.0; +https://github.com/lonion-1/WhaleGuard)",
    "Accept": "application/json",
}


def _fetch_json(ctx: Ctx, path: str, deadline: Deadline):
    for base in ("https://www.reddit.com", "https://old.reddit.com"):
        if ctx.http.is_tripped(base):
            continue
        r = ctx.http.get(base + path, timeout=18, retries=1, max_bytes=2_500_000, deadline=deadline, headers=REDDIT_HEADERS)
        if r.ok and r.text:
            try:
                return json.loads(r.text)
            except ValueError:
                return None
        if r.kind in ("blocked", "transient"):
            continue
    return None


def _walk_comments(children: list, out_texts: list[str], depth: int = 0) -> None:
    if depth > 6 or not isinstance(children, list):
        return
    for item in children:
        if not isinstance(item, dict):
            continue
        data = item.get("data") or {}
        body = data.get("body")
        if isinstance(body, str) and body and body not in ("[deleted]", "[removed]"):
            out_texts.append(body)
        replies = data.get("replies")
        if isinstance(replies, dict):
            _walk_comments((replies.get("data") or {}).get("children", []), out_texts, depth + 1)


def run(ctx: Ctx, st: dict, deadline: Deadline) -> CollectorResult:
    cfg, T, ts = ctx.cfg, ctx.cfg.T, ctx.ts
    stats: dict = {"queries": 0, "threads": 0, "found": 0}
    if not T.get("reddit_enabled", True):
        return CollectorResult("reddit", stats=stats)

    sightings = []
    tg_out: list[tuple[str, str]] = []
    web_out: list[tuple[str, str, int]] = []
    seen_posts: dict[str, int] = st.setdefault("seen_posts", {})

    if len(seen_posts) > T["reddit_seen_max"]:
        keep = sorted(seen_posts.items(), key=lambda kv: kv[1], reverse=True)[:T["reddit_seen_max"]]
        seen_posts.clear()
        seen_posts.update(keep)

    endpoints: list[tuple[str, str]] = []
    if cfg.queries_reddit:
        q_cur = int(st.get("query_cursor", 0)) % len(cfg.queries_reddit)
        for i in range(min(T["reddit_queries_per_run"], len(cfg.queries_reddit))):
            idx = (q_cur + i) % len(cfg.queries_reddit)
            q = cfg.queries_reddit[idx]
            endpoints.append((
                f"search:{q}",
                f"/search.json?q={urllib.parse.quote_plus(q)}&sort=new&t=month&limit={T['reddit_posts_limit']}&raw_json=1",
            ))
        st["query_cursor"] = (q_cur + len(endpoints)) % len(cfg.queries_reddit)

    if cfg.seeds_reddit:
        s_cur = int(st.get("sub_cursor", 0)) % len(cfg.seeds_reddit)
        n_sub = min(T["reddit_subreddits_per_run"], len(cfg.seeds_reddit))
        for i in range(n_sub):
            idx = (s_cur + i) % len(cfg.seeds_reddit)
            sub = cfg.seeds_reddit[idx]
            endpoints.append((
                f"r/{sub}",
                f"/r/{urllib.parse.quote(sub)}/new.json?limit={T['reddit_posts_limit']}&raw_json=1",
            ))
        st["sub_cursor"] = (s_cur + n_sub) % len(cfg.seeds_reddit)

    threads_to_expand: list[tuple[str, str, str]] = []

    for label, path in endpoints:
        if deadline.expired(10):
            stats["time_up"] = 1
            break
        data = _fetch_json(ctx, path, deadline)
        if not isinstance(data, dict):
            if ctx.http.is_tripped("reddit.com") and ctx.http.is_tripped("old.reddit.com"):
                log("REDDIT", "Reddit membatasi akses IP runner → dilewati sisa run ini")
                break
            polite(ctx, deadline, 1.5)
            continue

        stats["queries"] += 1
        children = ((data.get("data") or {}).get("children")) or []
        for child in children:
            p = (child or {}).get("data") or {}
            pid = str(p.get("name") or p.get("id") or "")
            if not pid:
                continue
            sub = str(p.get("subreddit") or "reddit")
            title = str(p.get("title") or "")
            selftext = str(p.get("selftext") or "")
            ext_url = str(p.get("url") or "")
            permalink = str(p.get("permalink") or "")
            num_comments = int(p.get("num_comments") or 0)

            blob = norm_text(f"{title}\n{selftext}\n{ext_url}")
            is_relevant = bool(cfg.re_topic.search(blob))
            is_indo = len(cfg.re_indo.findall(blob)) >= 2 or sub.lower() in {s.lower() for s in cfg.seeds_reddit}

            if not (is_relevant and is_indo):
                continue

            src_tag = f"reddit:r/{sub}"
            if pid not in seen_posts:
                s_list = extract_phone_sightings(ctx, blob, src_tag, has_page_context=True)
                sightings.extend(s_list)
                stats["found"] += len(s_list)

                tgs, webs = extract_outbound_links(cfg, blob, [ext_url] if ext_url else None)
                for u in tgs:
                    tg_out.append((u, src_tag))
                for w in webs:
                    web_out.append((w, src_tag, 1))
                seen_posts[pid] = int(ts)

            if permalink and num_comments > 0 and len(threads_to_expand) < T["reddit_comments_per_run"]:
                threads_to_expand.append((pid, permalink, src_tag))

        polite(ctx, deadline, 1.5)

    for pid, permalink, src_tag in threads_to_expand:
        if deadline.expired(8):
            break
        clean_perm = permalink.split("?", 1)[0].rstrip("/") + ".json?limit=80&raw_json=1"
        tree = _fetch_json(ctx, clean_perm, deadline)
        if not isinstance(tree, list) or len(tree) < 2:
            polite(ctx, deadline, 1.2)
            continue
        stats["threads"] += 1
        comment_texts: list[str] = []
        _walk_comments(((tree[1].get("data") or {}).get("children")) or [], comment_texts)
        for c_txt in comment_texts:
            s_list = extract_phone_sightings(ctx, c_txt, src_tag, has_page_context=True)
            sightings.extend(s_list)
            stats["found"] += len(s_list)
            tgs, webs = extract_outbound_links(cfg, c_txt)
            for u in tgs:
                tg_out.append((u, src_tag))
            for w in webs:
                web_out.append((w, src_tag, 1))
        polite(ctx, deadline, 1.5)

    log("REDDIT", f"{stats['queries']} query/sub, {stats['threads']} thread komentar, +{stats['found']} nomor")
    return CollectorResult("reddit", sightings, tg_out, web_out, stats)
          

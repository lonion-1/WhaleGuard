# Copyright (c) 2026 EazyWhale (https://github.com/lonion-1/WhaleGuard)
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pipeline bersama: gabungkan temuan lintas-sumber -> skor -> anti-false-positive -> tulis rules."""
from __future__ import annotations

import os

from .core import DAY, RULES_FILE, Ctx, PhoneSighting, log
from .extractor import nomor_ke_regex

DEFAULT_STATE = {"version": 9, "numbers": {}}


def total_score(entry: dict) -> int:
    return sum(int(v) for v in entry.get("src", {}).values())


def merge(nums: dict, sightings: list[PhoneSighting], ts: float) -> int:
    added = 0
    for s in sightings:
        p = nums.get(s.number)
        if p is None:
            p = nums[s.number] = {
                "src": {},
                "first": int(ts),
                "last": int(ts),
                "notes": [],
            }
            added += 1
        p["last"] = int(ts)
        p["src"][s.source] = max(int(p["src"].get(s.source, 0)), int(s.pts))
        if s.note and s.note not in p["notes"] and len(p["notes"]) < 5:
            p["notes"].append(s.note)
        if len(p["src"]) > 10:
            for k in sorted(p["src"], key=p["src"].get)[: len(p["src"]) - 10]:
                p["src"].pop(k, None)
    return added


def tulis_rules(numbers: list[str]) -> None:
    RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = RULES_FILE.read_text(encoding="utf-8", errors="ignore") if RULES_FILE.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    baris_baru = "".join(f"{nomor_ke_regex(n)}\n" for n in sorted(numbers))
    tmp = RULES_FILE.with_name(RULES_FILE.name + ".tmp")
    tmp.write_text(existing + baris_baru, encoding="utf-8")
    os.replace(tmp, RULES_FILE)


def finalize(ctx: Ctx, store) -> tuple[list[str], dict]:
    T, ts = ctx.cfg.T, ctx.ts
    nums = store.data["numbers"]
    ignore = ctx.known_numbers | ctx.allowlist_numbers
    stats = {"pending": 0, "promoted": 0, "capped": 0}

    for n in list(nums):
        p = nums[n]
        if n in ignore or ts - p.get("last", 0) > T["pending_ttl_days"] * DAY:
            del nums[n]

    if len(nums) > T["pending_max"]:
        keep = sorted(nums, key=lambda n: (total_score(nums[n]), nums[n]["last"]), reverse=True)[: T["pending_max"]]
        keep_set = set(keep)
        for n in [n for n in nums if n not in keep_set]:
            del nums[n]

    ready = [n for n, p in nums.items() if total_score(p) >= T["promote_at"]]
    promoted: list[str] = []
    per_src: dict[str, int] = {}

    for n in sorted(ready, key=lambda x: (-total_score(nums[x]), x)):
        if len(promoted) >= T["max_new_numbers_per_run"]:
            stats["capped"] += 1
            continue
        p = nums[n]
        top_src = max(p["src"], key=p["src"].get)
        if per_src.get(top_src, 0) >= T["max_promoted_per_source"]:
            stats["capped"] += 1
            continue
        per_src[top_src] = per_src.get(top_src, 0) + 1
        promoted.append(n)

    skor_map = {n: total_score(nums[n]) for n in promoted}
    if promoted and not ctx.dry:
        tulis_rules(promoted)

    for n in promoted:
        if not ctx.dry:
            nums.pop(n, None)
        ctx.known_numbers.add(n)
        log("+NOMOR", f"{n}  (skor {skor_map[n]})")

    stats["promoted"] = len(promoted)
    stats["pending"] = len(nums)
    return promoted, stats
      

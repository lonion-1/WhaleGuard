# Copyright (c) 2026 EazyWhale (https://github.com/lonion-1/WhaleGuard)
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Radar Nomor v9 — Orkestrator multi-sumber (Telegram, Reddit, Open Web & Facebook Publik)."""
from __future__ import annotations

import argparse
import json
import os
import time
import traceback

from . import pipeline, reddit, telegram, web_open
from .core import (
    DAY, LEGACY_DISCOVERY, LEGACY_SEEN, CollectorResult, Config, ConfigError, Ctx,
    Deadline, Http, Store, load_config, log, now,
)
from .extractor import extract_phone_sightings, load_known_numbers, normalisasi_nomor


def migrate_legacy(tg: Store, ts: float, T: dict) -> None:
    if tg.existed or (not LEGACY_DISCOVERY.exists() and not LEGACY_SEEN.exists()):
        return
    last_posts: dict[str, int] = {}
    if LEGACY_SEEN.exists():
        try:
            seen_arr = json.loads(LEGACY_SEEN.read_text(encoding="utf-8"))
            if isinstance(seen_arr, list):
                for item in seen_arr:
                    s = str(item)
                    if s.startswith("tg:") and "/" in s:
                        ch_part, num_part = s[3:].rsplit("/", 1)
                        if num_part.isdigit():
                            last_posts[ch_part] = max(last_posts.get(ch_part, 0), int(num_part))
        except Exception as e:
            log("MIGRASI", f"nomor_radar_seen.json lama gagal dibaca ({e})")

    if LEGACY_DISCOVERY.exists():
        try:
            old = json.loads(LEGACY_DISCOVERY.read_text(encoding="utf-8"))
            for ch, m in (old.get("channels") or {}).items():
                meta = telegram.new_meta(m.get("source", "legacy"))
                meta["scans"] = int(m.get("scans", 0))
                meta["harvested"] = int(m.get("harvested", 0))
                meta["dry_runs"] = int(m.get("dry_runs", 0))
                meta["last_post"] = last_posts.get(ch, 0)
                tg.data["channels"][ch] = meta
            stamp = int(ts - (T["reject_recheck_days"] - 3) * DAY)
            for r in old.get("rejected", []):
                tg.data["rejected"][str(r).lower()] = stamp
        except Exception as e:
            log("MIGRASI", f"discovered_channels.json lama gagal dibaca ({e})")

    log(
        "MIGRASI",
        f"State v8 diimpor: {len(tg.data['channels'])} kanal TG, "
        f"{len(last_posts)} kursor last_post terpulihkan",
    )


def check_config(cfg: Config) -> int:
    log("CONFIG", "✔ Semua file config/nomor_*.toml valid")
    log(
        "CONFIG",
        f"Seed: {len(cfg.seeds_tg)} kanal TG, {len(cfg.seeds_reddit)} subreddit, {len(cfg.seeds_web)} web | "
        f"Query: {len(cfg.queries_tg)} TG, {len(cfg.queries_reddit)} Reddit",
    )
    for w in cfg.warnings:
        log("CONFIG", f"⚠ {w}")

    dummy_ctx = Ctx(cfg, Http(cfg.T), set(), set(), now(), dry=True)
    samples = [
        ("Laporan penipu eksplisit", "Waspada nomor penipu 0812-3456-7899 modus undangan apk"),
        ("Penyamaran CS bank", "Hati-hati penipu 085712345678 mengaku CS resmi BCA"),
        ("CS resmi sah", "Untuk keluhan silakan hubungi CS resmi Halo BCA 081299887766"),
        ("Iklan jualan motor", "Dijual motor matic pajak hidup harga nego minat hubungi 081344556677"),
        ("Link WhatsApp pinjol", "Diteror DC pinjol lewat wa.me/6287811223344 sebar data kontak"),
        ("Nomor dummy", "Contoh format nomor 08123456789 jangan ditransfer"),
    ]
    for label, text in samples:
        res = extract_phone_sightings(dummy_ctx, text, "test", has_page_context=True)
        out = f"{res[0].number} (skor={res[0].pts}, {res[0].note})" if res else "DIABAIKAN"
        log("TEST", f"{label:26} → {out}")

    norm_test = normalisasi_nomor(cfg, "+62 812-9988-7766")
    assert norm_test == "081299887766", f"Normalisasi gagal: {norm_test}"
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="WhaleGuard Radar Nomor v9")
    ap.add_argument("--check-config", action="store_true", help="validasi config & jalankan uji contoh")
    ap.add_argument("--dry-run", action="store_true", help="jalan penuh tanpa menulis file apa pun")
    ap.add_argument("--only", default="", help="koma: telegram,reddit,web (default semua)")
    ap.add_argument("--budget", type=int, default=0, help="timpa time_budget_seconds")
    args = ap.parse_args(argv)

    try:
        cfg = load_config()
    except ConfigError as e:
        log("CONFIG", f"GAGAL: {e}")
        return 2

    if args.check_config:
        return check_config(cfg)

    for w in cfg.warnings:
        log("CONFIG", f"peringatan: {w}")

    T = cfg.T
    budget = args.budget or T["time_budget_seconds"]
    collect_dl = Deadline(max(30.0, budget - T["finalize_reserve_seconds"]))
    ts = now()
    ctx = Ctx(cfg, Http(T), set(), set(), ts, dry=args.dry_run)
    only = {x.strip().lower() for x in args.only.split(",") if x.strip()}

    if args.dry_run:
        log("MODE", "DRY-RUN: tidak ada file yang ditulis")

    load_known_numbers(ctx)
    log("CACHE", f"{len(ctx.known_numbers)} nomor sudah diblokir, {len(ctx.allowlist_numbers)} allowlist")

    st_tg = Store("telegram", telegram.DEFAULT_STATE).load()
    st_rd = Store("reddit", reddit.DEFAULT_STATE).load()
    st_web = Store("web", web_open.DEFAULT_STATE).load()
    st_pend = Store("pending", pipeline.DEFAULT_STATE).load()

    migrate_legacy(st_tg, ts, T)

    results: list[CollectorResult] = []
    tg_snowball: list[tuple[str, str]] = []
    web_snowball: list[tuple[str, str, int]] = []

    def guarded(name: str, store: Store, fn, weight_left: int, w: int) -> None:
        if only and name not in only:
            return
        dl = collect_dl.sub(collect_dl.left() * w / max(1, weight_left))
        t0 = time.monotonic()
        try:
            res = fn(dl)
        except Exception as e:
            log("ERROR", f"collector {name} crash: {e!r}")
            traceback.print_exc()
            res = CollectorResult(name, error=repr(e))
        finally:
            try:
                store.save(args.dry_run)
            except Exception as e:
                log("ERROR", f"gagal simpan state {name}: {e!r}")
        res.stats["detik"] = round(time.monotonic() - t0)
        results.append(res)
        tg_snowball.extend(res.tg_candidates)
        web_snowball.extend(res.web_candidates)

    guarded("reddit", st_rd, lambda dl: reddit.run(ctx, st_rd.data, dl), 10, 3)
    guarded("telegram", st_tg, lambda dl: telegram.run(ctx, st_tg.data, dl, tg_snowball), 7, 4)
    guarded("web", st_web, lambda dl: web_open.run(ctx, st_web.data, dl, web_snowball), 3, 3)

    for r in results:
        added = pipeline.merge(st_pend.data["numbers"], r.sightings, ts)
        log("MERGE", f"{r.name}: {len(r.sightings)} temuan ({added} nomor baru di pending)")

    promoted: list[str] = []
    fin_stats: dict = {}
    try:
        promoted, fin_stats = pipeline.finalize(ctx, st_pend)
    except Exception as e:
        log("ERROR", f"finalisasi crash: {e!r}")
        traceback.print_exc()
    finally:
        st_pend.save(args.dry_run)

    ringkasan(results, promoted, fin_stats, args.dry_run)
    crashed = [r for r in results if r.error]
    if results and len(crashed) == len(results):
        return 1
    if not promoted:
        log("HASIL", "0 nomor baru yang lolos skor promosi.")
    return 0


def ringkasan(results: list[CollectorResult], promoted: list[str], fin: dict, dry: bool) -> None:
    lines = [
        "## 📱 WhaleGuard Radar Nomor v9" + (" (dry-run)" if dry else ""),
        "",
        "| Collector | Status | Statistik |",
        "|---|---|---|",
    ]
    for r in results:
        stat = ", ".join(f"{k}={v}" for k, v in r.stats.items())
        lines.append(f"| {r.name} | {'❌ ' + r.error if r.error else '✅'} | {stat} |")
    lines += ["", "**Pipeline:** " + ", ".join(f"{k}={v}" for k, v in fin.items()), ""]
    if promoted:
        lines += [f"**{len(promoted)} nomor baru ditambahkan:**", ""] + [f"- `{n}`" for n in promoted[:60]]

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError:
            pass
      

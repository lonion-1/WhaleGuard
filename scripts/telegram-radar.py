# Copyright (c) 2026 <EazyWhale>
# Licensed under the MIT License.
"""WhaleGuard Radar: kumpulkan nomor/modus penipuan dari channel Telegram publik.

Sumber: halaman pratinjau publik https://t.me/s/<channel> (tanpa login/API key).
Output: radar_report.md (isi issue) + flag has_findings di $GITHUB_OUTPUT.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

# Isi dengan username channel PUBLIK (tanpa @) yang relevan.
CHANNELS = [
    # "contoh_channel_laporan_penipuan",
]

MAX_PAGES = 5          # halaman per channel (~20 pesan/halaman)
MAX_STATE = 3000       # jumlah ID terakhir yang diingat
MAX_MODUS = 10         # maksimal diskusi modus per laporan
STATE_FILE = Path(".github/radar_seen.json")
REPORT_FILE = Path("radar_report.md")

# Nomor HP Indonesia: 08xx / 628xx / +628xx (10-14 digit)
RE_PHONE = re.compile(r"(?<![\d+])(?:\+62|62|0)8[1-9](?:[ .\-]?\d){6,10}(?!\d)")


def normalisasi(nomor: str) -> str:
    d = re.sub(r"\D", "", nomor)
    return "0" + d[2:] if d.startswith("62") else d


def aman(teks: str, batas: int | None = None) -> str:
    """Bersihkan teks pihak luar sebelum masuk markdown issue."""
    t = re.sub(r"\s+", " ", teks or "").strip()
    dipotong = batas is not None and len(t) > batas
    if dipotong:
        t = t[:batas].rstrip()
    t = t.replace("@", "@\u200b")                # cegah ping user/org
    t = re.sub(r"#(?=\d)", "#\u200b", t)        # cegah auto-link issue
    t = t.replace("[", "(").replace("]", ")").replace("`", "'")
    t = t.replace("<", "‹").replace(">", "›").replace("|", "¦")
    return t + ("…" if dipotong else "")


class TgParser(HTMLParser):
    """Ambil (data-post, teks) dari halaman t.me/s/<channel>."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.msgs: list[dict] = []
        self.cur = None
        self.in_text = False
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if tag == "div" and "tgme_widget_message" in cls and a.get("data-post"):
            self.cur = {"post": a["data-post"], "text": []}
            self.msgs.append(self.cur)
        elif (self.cur is not None and tag == "div"
              and "tgme_widget_message_text" in cls
              and "js-message_reply_text" not in cls):
            self.in_text, self.depth = True, 1
        elif self.in_text:
            if tag == "div":
                self.depth += 1
            elif tag == "br":
                self.cur["text"].append(" ")

    def handle_endtag(self, tag):
        if self.in_text and tag == "div":
            self.depth -= 1
            if self.depth == 0:
                self.in_text = False

    def handle_data(self, data):
        if self.in_text and self.cur is not None:
            self.cur["text"].append(data)


def fetch_page(channel: str, before: int | None = None) -> list[dict] | None:
    url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; WhaleGuard-Radar/3.0; +https://github.com/lonion-1/WhaleGuard)",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            page = r.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[ERROR] {url}: {e}")
        return None
    p = TgParser()
    p.feed(page)
    return [{"id": m["post"], "text": "".join(m["text"]).strip()} for m in p.msgs]


def fetch_channel(channel: str, seen: set[str]) -> list[dict] | None:
    """Ambil pesan terbaru, mundur per halaman sampai ketemu yang sudah dilihat."""
    hasil, before = [], None
    for _ in range(MAX_PAGES):
        msgs = fetch_page(channel, before)
        if msgs is None:
            return None if not hasil else hasil
        if not msgs:
            if before is None:
                print(f"[WARN] {channel}: tidak ada pesan (channel privat / pratinjau mati?).")
            break
        hasil.extend(msgs)
        if any(f"tg:{m['id']}" in seen for m in msgs):
            break
        try:
            before = min(int(m["id"].rsplit("/", 1)[1]) for m in msgs)
        except (ValueError, IndexError):
            break
    print(f"[OK] {channel}: {len(hasil)} pesan dibaca.")
    return hasil


def main() -> int:
    clean_channels = [c.strip().lstrip("@") for c in CHANNELS if c.strip().lstrip("@")]
    if not clean_channels:
        print("[ERROR] CHANNELS kosong. Isi daftar channel publik dulu.")
        return 1

    seen_list: list[str] = []
    if STATE_FILE.exists():
        try:
            seen_list = list(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except Exception:
            seen_list = []
    seen = set(seen_list)

    temuan_nomor, temuan_modus = [], []
    gagal = 0

    for ch in clean_channels:
        msgs = fetch_channel(ch, seen)
        if msgs is None:
            gagal += 1
            continue
        for m in sorted(msgs, key=lambda x: int(x["id"].rsplit("/", 1)[1])):
            sid = f"tg:{m['id']}"
            if sid in seen or not m["text"]:
                continue
            nomor = sorted({normalisasi(x.group(0)) for x in RE_PHONE.finditer(m["text"])})
            item = {
                "sid": sid,
                "url": f"https://t.me/{m['id']}",
                "channel": m["id"].split("/")[0],
                "numbers": nomor,
                "snippet": aman(m["text"], 300),
            }
            (temuan_nomor if nomor else temuan_modus).append(item)

    modus_tampil = temuan_modus[-MAX_MODUS:]
    modus_sisa = len(temuan_modus) - len(modus_tampil)
    for it in temuan_nomor + modus_tampil:
        seen_list.append(it["sid"])
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(seen_list[-MAX_STATE:], indent=2) + "\n", encoding="utf-8")

    gh_out = os.environ.get("GITHUB_OUTPUT")

    def set_output(val: bool):
        if gh_out:
            with open(gh_out, "a", encoding="utf-8") as f:
                f.write(f"has_findings={'true' if val else 'false'}\n")

    if gagal == len(clean_channels):
        print("[ERROR] Semua channel gagal diakses.")
        set_output(False)
        return 1

    if not temuan_nomor and not modus_tampil:
        print("Radar Telegram: tidak ada pesan baru.")
        set_output(False)
        return 0

    L = [
        "### 📡 Laporan Radar Telegram (`WhaleGuard`)",
        f"Ditemukan **{len(temuan_nomor)}** pesan dengan nomor telepon & "
        f"**{len(temuan_modus)}** pesan modus/spam baru.",
        "",
    ]
    if temuan_nomor:
        L.append("#### 📞 Pesan dengan Nomor Terdeteksi")
        for it in temuan_nomor:
            nums = ", ".join(f"`{n}`" for n in it["numbers"])
            L.append(f"* [{it['channel']}]({it['url']}) — {nums}")
            L.append(f"  * Cuplikan: *{it['snippet']}*")
        L.append("")
    if modus_tampil:
        L.append("#### 🕵️ Modus Penipuan / Spam (cek pola SMS baru)")
        for it in modus_tampil:
            L.append(f"* [{it['channel']}]({it['url']})")
            L.append(f"  * Cuplikan: *{it['snippet']}*")
        if modus_sisa:
            L.append(f"* …dan {modus_sisa} pesan lain (akan muncul di laporan berikutnya).")
        L.append("")
    L += ["---",
          "*Catatan: nomor di pesan belum tentu milik penipu (bisa korban/salah tulis). "
          "Periksa sumber sebelum menambahkan nomor atau regex baru ke `rules/`.*"]

    body = "\n".join(L)
    REPORT_FILE.write_text(body + "\n", encoding="utf-8")
    print("\n" + body)
    set_output(True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

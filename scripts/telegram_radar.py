# Copyright (c) 2026 <EazyWhale>
# Licensed under the MIT License.
"""WhaleGuard Radar: pantau laporan penipuan & pinjol dari channel publik Telegram.

Mode ganda:
1. Auto-Hunt global channel publik Telegram (site:t.me/s/) tanpa perlu daftar channel manual.
2. Direct Scrape opsional jika EXTRA_CHANNELS diisi username channel publik.

Output: radar_report.md (isi issue) + flag has_findings di $GITHUB_OUTPUT.
"""
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

# Opsional: isi username channel publik (tanpa @) jika ingin dipantau langsung per halaman.
# Boleh dibiarkan kosong [] karena Auto-Hunt di bawah sudah jalan otomatis!
EXTRA_CHANNELS: list[str] = [
    # "contoh_channel_publik",
]

TARGETS = [
    ("Telegram Pinjol & DC", 'site:t.me/s/ (pinjol OR galbay OR "debt collector" OR penipu OR penipuan)'),
    ("Telegram Waspada Penipuan", 'site:t.me/s/ (penipu OR penipuan OR "nomor penipu" OR scam OR apk)'),
    ("Telegram Judol & Smishing", 'site:t.me/s/ (judol OR "slot gacor" OR "dana kaget" OR phishing)'),
]

MAX_PAGES = 3
MAX_STATE = 2000
MAX_MODUS = 12
STATE_FILE = Path(".github/radar_seen.json")
REPORT_FILE = Path("radar_report.md")

# Nomor HP Indonesia: 08xx / 628xx / +628xx (10-14 digit)
RE_PHONE = re.compile(r"(?<![\d+])(?:\+62|62|0)8[1-9](?:[ .\-]?\d){6,10}(?!\d)")

# Gerbang wajib: konten HARUS relevan dengan penipuan, pinjol, judol, atau spam
RE_RELEVANT = re.compile(
    r"(?i)\b("
    r"penipu\w*|scam\w*|pinjol|galbay|dc\b|debt\s*collector|"
    r"judol|judi|slot|gacor|phishing|smishing|malware|apk|"
    r"spam\w*|otp|kurir|resi|tilang|dana\s*kaget|investasi\s*bodong|"
    r"loker\s*fiktif|blokir\s*rekening|hack\w*|bocor|sebar\s*data"
    r")\b"
)


def normalisasi(nomor: str) -> str:
    d = re.sub(r"\D", "", nomor)
    return "0" + d[2:] if d.startswith("62") else d


def aman(teks: str, batas: int | None = None) -> str:
    """Bersihkan teks eksternal sebelum masuk Markdown Issue GitHub."""
    t = re.sub(r"\s+", " ", teks or "").strip()
    dipotong = batas is not None and len(t) > batas
    if dipotong:
        t = t[:batas].rstrip()
    t = t.replace("@", "@\u200b")              # cegah ping akun GitHub
    t = re.sub(r"#(?=\d)", "#\u200b", t)      # cegah auto-link nomor issue
    t = t.replace("[", "(").replace("]", ")").replace("`", "'")
    t = t.replace("<", "‹").replace(">", "›").replace("|", "¦")
    return t + ("…" if dipotong else "")


def bersihkan_html(raw_html: str) -> str:
    teks = re.sub(r"<[^>]+>", " ", html.unescape(raw_html or ""))
    return re.sub(r"\s+", " ", teks).strip()


def fetch_tg_bridge(label: str, query: str) -> list[dict] | None:
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=id&gl=ID&ceid=ID:id"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; WhaleGuard-Radar/4.2; +https://github.com/lonion-1/WhaleGuard)",
            "Accept": "application/rss+xml, application/xml, text/xml",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            xml_data = r.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[ERROR] Gagal akses bridge ({label}): {e}")
        return None

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        print(f"[ERROR] Gagal parsing XML ({label}): {e}")
        return None

    items = root.findall(".//item")
    hasil = []
    for it in items:
        title_raw = (it.findtext("title") or "").strip()
        title = re.sub(r"\s*-\s*Telegram\s*$", "", title_raw, flags=re.IGNORECASE).strip()
        link = (it.findtext("link") or "").strip()
        guid = (it.findtext("guid") or link).strip()
        desc = bersihkan_html(it.findtext("description") or "")

        if not title or not RE_RELEVANT.search(f"{title} {desc}"):
            continue

        if guid and link:
            hasil.append({
                "id": f"tg-idx:{guid}",
                "title": title,
                "url": link,
                "text": desc,
            })

    print(f"[OK] {label} -> {len(hasil)} postingan relevan (dari {len(items)} indeks).")
    return hasil


class TgParser(HTMLParser):
    """Ambil (data-post, teks) dari halaman langsung t.me/s/<channel>."""

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


def fetch_direct_channel(channel: str, seen: set[str]) -> list[dict]:
    hasil, before = [], None
    for _ in range(MAX_PAGES):
        url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; WhaleGuard-Radar/4.2; +https://github.com/lonion-1/WhaleGuard)",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                page = r.read().decode("utf-8", errors="ignore")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            print(f"[ERROR] {url}: {e}")
            break
        p = TgParser()
        p.feed(page)
        if not p.msgs:
            break
        for m in p.msgs:
            txt = "".join(m["text"]).strip()
            if txt and RE_RELEVANT.search(txt):
                hasil.append({
                    "id": f"tg:{m['post']}",
                    "title": f"Channel @{channel}",
                    "url": f"https://t.me/{m['post']}",
                    "text": txt,
                })
        if any(f"tg:{m['post']}" in seen for m in p.msgs):
            break
        try:
            before = min(int(m["post"].rsplit("/", 1)[1]) for m in p.msgs)
        except (ValueError, IndexError):
            break
    print(f"[OK] Direct @{channel} -> {len(hasil)} pesan relevan.")
    return hasil


def main() -> int:
    seen_list: list[str] = []
    if STATE_FILE.exists():
        try:
            seen_list = list(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except Exception:
            seen_list = []
    seen = set(seen_list)

    kandidat: list[dict] = []
    gagal = 0

    for label, q in TARGETS:
        posts = fetch_tg_bridge(label, q)
        if posts is None:
            gagal += 1
        else:
            kandidat.extend(posts)

    for raw_ch in EXTRA_CHANNELS:
        ch = raw_ch.strip().lstrip("@")
        if ch:
            kandidat.extend(fetch_direct_channel(ch, seen))

    temuan_nomor, temuan_modus = [], []
    for post in kandidat:
        sid = post["id"]
        if sid in seen:
            continue
        seen.add(sid)

        gabungan = f"{post['title']}\n{post['text']}"
        nomor = sorted({normalisasi(m.group(0)) for m in RE_PHONE.finditer(gabungan)})

        item = {
            "sid": sid,
            "title": aman(post["title"], 140),
            "url": post["url"],
            "numbers": nomor,
            "snippet": aman(post["text"], 300),
        }
        (temuan_nomor if nomor else temuan_modus).append(item)

    modus_tampil = temuan_modus[:MAX_MODUS]
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

    if gagal == len(TARGETS) and not EXTRA_CHANNELS:
        print("[ERROR] Semua target Telegram gagal diakses.")
        set_output(False)
        return 1

    if not temuan_nomor and not modus_tampil:
        print("Radar Telegram: tidak ada laporan baru yang relevan.")
        set_output(False)
        return 0

    L = [
        "### 📡 Laporan Radar Intelijen Telegram (`WhaleGuard`)",
        f"Ditemukan **{len(temuan_nomor)}** pesan dengan nomor telepon & "
        f"**{len(temuan_modus)}** postingan channel modus/spam baru:",
        "",
    ]

    if temuan_nomor:
        L.append("#### 📞 Pesan dengan Nomor Terdeteksi")
        for it in temuan_nomor:
            nums = ", ".join(f"`{n}`" for n in it["numbers"])
            L.append(f"* [{it['title']}]({it['url']}) — {nums}")
            if it["snippet"]:
                L.append(f"  * Cuplikan: *{it['snippet']}*")
        L.append("")

    if modus_tampil:
        L.append("#### 🕵️ Postingan Channel Pinjol / Penipuan (Cek Pola SMS Baru)")
        for it in modus_tampil:
            L.append(f"* [{it['title']}]({it['url']})")
            if it["snippet"]:
                L.append(f"  * Cuplikan: *{it['snippet']}*")
        if modus_sisa:
            L.append(f"* …dan {modus_sisa} pesan lain (akan muncul di laporan berikutnya).")
        L.append("")

    L += [
        "---",
        "*Catatan: Pastikan nomor/pola di atas valid dari pelaku (bukan nomor korban yang bocor) "
        "sebelum menambahkannya ke `rules/`.*",
    ]

    body = "\n".join(L)
    REPORT_FILE.write_text(body + "\n", encoding="utf-8")
    print("\n" + body)
    set_output(True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

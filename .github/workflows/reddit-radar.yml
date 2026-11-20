# Copyright (c) 2026 <EazyWhale>
# Licensed under the MIT License.
"""WhaleGuard Radar: pantau laporan penipuan & modus SMS spam dari Reddit (RSS).

Output: reddit_report.md (isi issue) + flag has_findings di $GITHUB_OUTPUT.
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
from pathlib import Path

QUERIES = [
    # 1. Radar Utama Indonesia (Penipuan umum, pinjol, judol, kurir/APK)
    "subreddit:indonesia (penipu OR penipuan OR scam OR pinjol OR judol OR apk)",
    # 2. Radar Keuangan & Pinjol Ilegal Indonesia
    "subreddit:finansial (penipu OR penipuan OR pinjol OR phishing OR scam OR rekening)",
    # 3. Radar Teknologi & Spam Digital Indonesia
    "subreddit:indotech (penipu OR penipuan OR spam OR phishing OR scam)",
    # 4. Radar Global Khusus Konteks Indonesia / WhatsApp Smishing
    "subreddit:Scams (Indonesia OR WhatsApp OR smishing OR APK)",
    "subreddit:phishing (Indonesia OR smishing OR APK)",
]

MAX_STATE = 1000
MAX_MODUS = 12
STATE_FILE = Path(".github/reddit_seen.json")
REPORT_FILE = Path("reddit_report.md")

# Nomor HP Indonesia: 08xx / 628xx / +628xx (10-14 digit)
RE_PHONE = re.compile(r"(?<![\d+])(?:\+62|62|0)8[1-9](?:[ .\-]?\d){6,10}(?!\d)")


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


def fetch_reddit_rss(query: str) -> list[dict] | None:
    encoded = urllib.parse.quote(query)
    url = f"https://www.reddit.com/search.rss?q={encoded}&sort=new&t=month"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; WhaleGuard-Radar/3.0; +https://github.com/lonion-1/WhaleGuard)",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            xml_data = r.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[ERROR] Gagal akses RSS ({query}): {e}")
        return None

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        print(f"[ERROR] Gagal parsing XML ({query}): {e}")
        return None

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns)
    print(f"[OK] {query} -> {len(entries)} postingan.")

    hasil = []
    for entry in entries:
        id_el = entry.find("atom:id", ns)
        title_el = entry.find("atom:title", ns)
        link_el = entry.find("atom:link", ns)
        content_el = entry.find("atom:content", ns)

        pid = (id_el.text or "").strip() if id_el is not None else ""
        title = (title_el.text or "").strip() if title_el is not None else "(Tanpa Judul)"
        href = link_el.attrib.get("href", "") if link_el is not None else ""
        content_txt = bersihkan_html(content_el.text if content_el is not None else "")

        if pid:
            hasil.append({
                "id": f"rd:{pid}",
                "title": title,
                "url": href,
                "text": content_txt,
            })
    return hasil


def main() -> int:
    seen_list: list[str] = []
    if STATE_FILE.exists():
        try:
            seen_list = list(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except Exception:
            seen_list = []
    seen = set(seen_list)

    temuan_nomor, temuan_modus = [], []
    gagal = 0

    for q in QUERIES:
        posts = fetch_reddit_rss(q)
        if posts is None:
            gagal += 1
            continue

        for post in posts:
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

    if gagal == len(QUERIES):
        print("[ERROR] Semua query Reddit gagal diakses.")
        set_output(False)
        return 1

    if not temuan_nomor and not modus_tampil:
        print("Radar Reddit: tidak ada laporan baru.")
        set_output(False)
        return 0

    L = [
        "### 📡 Laporan Radar Intelijen Reddit (`WhaleGuard`)",
        f"Ditemukan **{len(temuan_nomor)}** laporan dengan nomor telepon & "
        f"**{len(temuan_modus)}** diskusi modus penipuan baru:",
        "",
    ]

    if temuan_nomor:
        L.append("#### 📞 Laporan dengan Nomor Telepon Terdeteksi")
        for it in temuan_nomor:
            nums = ", ".join(f"`{n}`" for n in it["numbers"])
            L.append(f"* [{it['title']}]({it['url']}) — {nums}")
            if it["snippet"]:
                L.append(f"  * Cuplikan: *{it['snippet']}*")
        L.append("")

    if modus_tampil:
        L.append("#### 🕵️ Diskusi Modus Penipuan / Spam (Cek Pola SMS Baru)")
        for it in modus_tampil:
            L.append(f"* [{it['title']}]({it['url']})")
            if it["snippet"]:
                L.append(f"  * Cuplikan: *{it['snippet']}*")
        if modus_sisa:
            L.append(f"* …dan {modus_sisa} diskusi lain (akan muncul di laporan berikutnya).")
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

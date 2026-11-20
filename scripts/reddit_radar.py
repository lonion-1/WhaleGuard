# Copyright (c) 2026 <EazyWhale>
# Licensed under the MIT License.
"""WhaleGuard Radar: pantau laporan penipuan & modus SMS spam dari Reddit (Filtered).

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

TARGETS = [
    ("r/indonesia", "site:reddit.com/r/indonesia intitle:(penipu OR penipuan OR pinjol OR judol OR scam OR apk OR spam)"),
    ("r/finansial", "site:reddit.com/r/finansial intitle:(penipu OR penipuan OR pinjol OR phishing OR scam OR rekening)"),
    ("r/indotech", "site:reddit.com/r/indotech intitle:(penipu OR penipuan OR spam OR phishing OR scam OR apk)"),
    ("r/Scams (ID)", "site:reddit.com/r/Scams (Indonesia OR WhatsApp OR APK) intitle:(scam OR phishing OR smishing OR WhatsApp)"),
]

MAX_STATE = 1000
MAX_MODUS = 12
STATE_FILE = Path(".github/reddit_seen.json")
REPORT_FILE = Path("reddit_report.md")

# Nomor HP Indonesia: 08xx / 628xx / +628xx (10-14 digit)
RE_PHONE = re.compile(r"(?<![\d+])(?:\+62|62|0)8[1-9](?:[ .\-]?\d){6,10}(?!\d)")

# Gerbang wajib: judul postingan HARUS mengandung minimal 1 kata kunci relevan
RE_RELEVANT = re.compile(
    r"(?i)\b("
    r"penipu\w*|scam\w*|pinjol|judol|judi|slot|gacor|"
    r"phishing|smishing|malware|apk|spam\w*|telemarket\w*|"
    r"otp|kurir|resi|tilang|dana\s*kaget|investasi\s*bodong|"
    r"loker\s*fiktif|blokir\s*rekening|hack\w*|bocor"
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


def fetch_google_bridge(label: str, query: str) -> list[dict] | None:
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=id&gl=ID&ceid=ID:id"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; WhaleGuard-Radar/4.1; +https://github.com/lonion-1/WhaleGuard)",
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
        title = re.sub(r"\s*-\s*Reddit\s*$", "", title_raw, flags=re.IGNORECASE).strip()
        link = (it.findtext("link") or "").strip()
        guid = (it.findtext("guid") or link).strip()
        desc = bersihkan_html(it.findtext("description") or "")

        # Buang halaman indeks subreddit kosong atau judul di luar topik penipuan/spam
        if not title or title.lower().startswith("r/") or not RE_RELEVANT.search(title):
            continue

        if guid and link:
            hasil.append({
                "id": f"gn:{guid}",
                "title": title,
                "url": link,
                "text": desc,
            })

    print(f"[OK] {label} -> {len(hasil)} postingan relevan (dari {len(items)} indeks).")
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

    for label, q in TARGETS:
        posts = fetch_google_bridge(label, q)
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

    if gagal == len(TARGETS):
        print("[ERROR] Semua target gagal diakses.")
        set_output(False)
        return 1

    if not temuan_nomor and not modus_tampil:
        print("Radar Reddit: tidak ada laporan baru yang relevan.")
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

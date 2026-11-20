# Copyright (c) 2026 <EazyWhale>
# Licensed under the MIT License.
"""WhaleGuard Unified Radar (Nomor-Only Mode).

Memindai Reddit, Facebook, dan Telegram sekaligus.
HANYA membuka Issue jika ditemukan nomor telepon Indonesia (08xx / +628xx).
Judul diskusi tanpa nomor telepon otomatis dibuang.
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
    # Reddit
    ("Reddit r/indonesia", "site:reddit.com/r/indonesia (penipu OR penipuan OR pinjol OR judol OR scam OR apk)"),
    ("Reddit r/finansial", "site:reddit.com/r/finansial (penipu OR penipuan OR pinjol OR phishing OR scam)"),
    ("Reddit r/indotech", "site:reddit.com/r/indotech (penipu OR penipuan OR spam OR phishing)"),
    # Facebook Publik
    ("Facebook Pinjol", 'site:facebook.com/groups (pinjol OR galbay OR "debt collector" OR penipu OR penipuan)'),
    ("Facebook Penipuan", 'site:facebook.com ("nomor penipu" OR "penipuan pinjol" OR "undangan apk" OR "paket penipu")'),
    # Telegram Publik
    ("Telegram Pinjol", 'site:t.me/s/ (pinjol OR galbay OR "debt collector" OR penipu OR penipuan)'),
    ("Telegram Penipuan", 'site:t.me/s/ (penipu OR penipuan OR "nomor penipu" OR scam OR judol)'),
]

MAX_STATE = 2500
STATE_FILE = Path(".github/nomor_radar_seen.json")
REPORT_FILE = Path("nomor_report.md")

RE_PHONE = re.compile(r"(?<![\d+])(?:\+62|62|0)8[1-9](?:[ .\-]?\d){6,10}(?!\d)")
DUMMY_NUMBERS = {
    "0812345678", "08123456789", "081234567890", "0812345678901",
    "08987654321", "081122334455",
}


def normalisasi(nomor: str) -> str | None:
    d = re.sub(r"\D", "", nomor)
    if d.startswith("62"):
        d = "0" + d[2:]
    if not re.fullmatch(r"08[1-9]\d{7,10}", d):
        return None
    if d in DUMMY_NUMBERS or len(set(d[2:])) == 1:
        return None
    return d


def aman(teks: str, batas: int = 160) -> str:
    t = re.sub(r"\s+", " ", teks or "").strip()
    if len(t) > batas:
        t = t[:batas].rstrip() + "…"
    t = t.replace("@", "@\u200b")
    t = re.sub(r"#(?=\d)", "#\u200b", t)
    t = t.replace("[", "(").replace("]", ")").replace("`", "'")
    return t.replace("<", "‹").replace(">", "›").replace("|", "¦")


def bersihkan_html(raw_html: str) -> str:
    teks = re.sub(r"<[^>]+>", " ", html.unescape(raw_html or ""))
    return re.sub(r"\s+", " ", teks).strip()


def fetch_rss(label: str, query: str) -> list[dict] | None:
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=id&gl=ID&ceid=ID:id"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; WhaleGuard-NomorRadar/5.0; +https://github.com/lonion-1/WhaleGuard)",
            "Accept": "application/rss+xml, application/xml, text/xml",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            xml_data = r.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[ERROR] {label}: {e}")
        return None

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        print(f"[ERROR] XML {label}: {e}")
        return None

    hasil = []
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        guid = (it.findtext("guid") or link).strip()
        desc = bersihkan_html(it.findtext("description") or "")
        if guid and link:
            hasil.append({
                "id": f"nr:{guid}",
                "source": label,
                "title": title,
                "url": link,
                "text": desc,
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

    temuan = []
    semua_nomor: set[str] = set()
    gagal = 0

    for label, q in TARGETS:
        posts = fetch_rss(label, q)
        if posts is None:
            gagal += 1
            continue

        for post in posts:
            sid = post["id"]
            if sid in seen:
                continue
            seen.add(sid)
            seen_list.append(sid)

            gabungan = f"{post['title']}\n{post['text']}"
            nomor_valid = sorted({
                n for m in RE_PHONE.finditer(gabungan)
                if (n := normalisasi(m.group(0))) is not None
            })

            # NOMOR-ONLY GATE: Tanpa nomor telepon = langsung buang!
            if not nomor_valid:
                continue

            semua_nomor.update(nomor_valid)
            temuan.append({
                "source": post["source"],
                "title": aman(post["title"], 120),
                "url": post["url"],
                "numbers": nomor_valid,
            })

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(seen_list[-MAX_STATE:], indent=2) + "\n", encoding="utf-8")

    gh_out = os.environ.get("GITHUB_OUTPUT")

    def set_output(val: bool):
        if gh_out:
            with open(gh_out, "a", encoding="utf-8") as f:
                f.write(f"has_findings={'true' if val else 'false'}\n")

    if gagal == len(TARGETS):
        print("[ERROR] Semua sumber gagal diakses.")
        set_output(False)
        return 1

    if not temuan:
        print("Radar Nomor: 0 nomor ditemukan. Tidak membuka Issue.")
        set_output(False)
        return 0

    daftar_siap_salin = "\n".join(sorted(semua_nomor))
    L = [
        "### 📞 Temuan Nomor Telepon Penipu (`WhaleGuard`)",
        f"Ditemukan **{len(semua_nomor)} nomor unik** dari **{len(temuan)} sumber**:",
        "",
        "#### 📋 Daftar Nomor Siap Salin (Tempel ke Form Lapor / `inbox/raw_numbers.txt`)",
        "```text",
        daftar_siap_salin,
        "```",
        "",
        "#### 🔎 Detail Sumber",
    ]
    for it in temuan:
        nums = ", ".join(f"`{n}`" for n in it["numbers"])
        L.append(f"* **[{it['source']}]** [{it['title']}]({it['url']}) $\\rightarrow$ {nums}")

    L += [
        "",
        "---",
        "*Filter Nomor-Only aktif: diskusi tanpa nomor telepon telah dibuang otomatis.*",
    ]

    body = "\n".join(L)
    REPORT_FILE.write_text(body + "\n", encoding="utf-8")
    print("\n" + body)
    set_output(True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

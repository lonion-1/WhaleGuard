# Copyright (c) 2026 EazyWhale (https://github.com/lonion-1/WhaleGuard)
# SPDX-License-Identifier: AGPL-3.0-or-later
# Licensed under the GNU Affero General Public License v3.0.
"""WhaleGuard Unified Radar (Full-Autopilot + Proximity Context Filter).

Memindai Reddit, Facebook, dan Telegram:
1. Mengecek konteks kalimat di sekitar nomor telepon (±80 karakter), bukan sekadar banner grup.
2. Menolak iklan jualan biasa (motor, makanan, jasa) yang kebetulan ada tulisan "hati-hati penipuan".
3. Melewati nomor yang sudah tercatat atau dilindungi rules/numbers-allowlist.txt.
4. Langsung mengonversi & menulis nomor valid ke rules/numbers-spam-id.txt.
"""
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

TARGETS = [
    ("Reddit r/indonesia", "site:reddit.com/r/indonesia (penipu OR penipuan OR pinjol OR judol OR scam OR apk)"),
    ("Reddit r/finansial", "site:reddit.com/r/finansial (penipu OR penipuan OR pinjol OR phishing OR scam)"),
    ("Reddit r/indotech", "site:reddit.com/r/indotech (penipu OR penipuan OR spam OR phishing)"),
    ("Facebook Pinjol", 'site:facebook.com/groups (pinjol OR galbay OR "debt collector" OR teror OR penipu)'),
    ("Facebook Penipuan", 'site:facebook.com ("nomor penipu" OR "no penipu" OR "akun penipu" OR "salahgunain" OR "undangan apk")'),
    ("Telegram Pinjol", 'site:t.me/s/ (pinjol OR galbay OR "debt collector" OR teror OR penipu)'),
    ("Telegram Penipuan", 'site:t.me/s/ ("nomor penipu" OR penipuan OR scam OR judol OR apk)'),
]

MAX_STATE = 2500
STATE_FILE = Path(".github/nomor_radar_seen.json")
RULES_FILE = Path("rules/numbers-spam-id.txt")
ALLOWLIST_FILE = Path("rules/numbers-allowlist.txt")

RE_PHONE = re.compile(r"(?<![\d+])(?:\+62|62|0)8[1-9](?:[ .\-]?\d){6,10}(?!\d)")
RE_EXISTING_RULE = re.compile(r"^\^?\(\\?\+62\|62\|0\)(8\d{8,11})\$?$")

# Kata kunci bukti kuat yang HARUS muncul dekat nomor telepon (±80 karakter)
RE_PROXIMITY_SCAM = re.compile(
    r"(?i)("
    r"\b(?:no|nomor|wa|whatsapp|tlp|telp)\s*(?:penipu|pelaku|dc|teror|dia|nya)\b|"
    r"\b(?:penipu|nipu|pelaku|scam\w*|salah\s*guna\w*|salahgunain|bajak|hack\w*)\b|"
    r"\b(?:pinjol|galbay|dc\b|debt\s*collector|teror\w*|ancam\w*|sebar\s*data|sebar\s*kontak)\b|"
    r"\b(?:judol|slot\s*gacor|phishing|smishing|malware|apk|undangan\s*apk)\b|"
    r"\b(?:akun\s*palsu|atas\s*nama|kronologi|viralkan|bantu\s*up)\b"
    r")"
)

# Ciri iklan jual-beli biasa (dibuang kecuali ada bukti penipuan eksplisit)
RE_COMMERCIAL_NOISE = re.compile(
    r"(?i)\b("
    r"dijual|jual\s*cepat|harga\s*nego|nego\s*di\s*tempat|cek\s*unit|"
    r"cash\s*dan\s*credit|ready\s*stok|ready\s*\d+|rb/kg|persediaan\s*terbatas|"
    r"full\s*ori|surat\s*lengkap|pajak\s*hidup|minat\s*hubungi|cod\s*sekitar"
    r")\b"
)

RE_EXPLICIT_REPORT = re.compile(
    r"(?i)\b(nomor\s*penipu|no\s*penipu|akun\s*penipu|salah\s*guna\w*|salahgunain|kronologi|viralkan)\b"
)

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


def nomor_ke_regex(norm_08: str) -> str:
    return rf"^(\+62|62|0){norm_08[1:]}$"


def muat_daftar_nomor(path: Path) -> set[str]:
    hasil: set[str] = set()
    if not path.exists():
        return hasil
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.split("#", 1)[0].strip()
        if not s:
            continue
        m = RE_EXISTING_RULE.match(s)
        if m:
            hasil.add("0" + m.group(1))
        elif (norm := normalisasi(s)) is not None:
            hasil.add(norm)
    return hasil


def bersihkan_html(raw_html: str) -> str:
    teks = re.sub(r"<[^>]+>", " ", html.unescape(raw_html or ""))
    return re.sub(r"\s+", " ", teks).strip()


def fetch_rss(label: str, query: str) -> list[dict] | None:
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=id&gl=ID&ceid=ID:id"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; WhaleGuard-NomorRadar/6.0; +https://github.com/lonion-1/WhaleGuard)",
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
                "text": desc,
            })
    return hasil


def ekstrak_nomor_valid(teks: str, diabaikan: set[str]) -> set[str]:
    """Ambil nomor HP hanya jika konteks ±80 karakter di sekitarnya terbukti laporan penipuan/pinjol."""
    # Buang iklan jual-beli biasa kecuali secara eksplisit melaporkan penipu
    if RE_COMMERCIAL_NOISE.search(teks) and not RE_EXPLICIT_REPORT.search(teks):
        return set()

    lolos: set[str] = set()
    for m in RE_PHONE.finditer(teks):
        norm = normalisasi(m.group(0))
        if norm is None or norm in diabaikan:
            continue

        mulai = max(0, m.start() - 80)
        akhir = min(len(teks), m.end() + 80)
        jendela_konteks = teks[mulai:akhir]

        if RE_PROXIMITY_SCAM.search(jendela_konteks):
            lolos.add(norm)

    return lolos


def main() -> int:
    sudah_blokir = muat_daftar_nomor(RULES_FILE)
    allowlist = muat_daftar_nomor(ALLOWLIST_FILE)
    diabaikan = sudah_blokir | allowlist

    seen_list: list[str] = []
    if STATE_FILE.exists():
        try:
            seen_list = list(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except Exception:
            seen_list = []
    seen = set(seen_list)

    nomor_baru: set[str] = set()
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

            gabungan = f"{post['title']} | {post['text']}"
            ditemukan = ekstrak_nomor_valid(gabungan, diabaikan | nomor_baru)
            if ditemukan:
                print(f"[+{len(ditemukan)}] {label}: {', '.join(sorted(ditemukan))} <- {post['title'][:90]}")
                nomor_baru.update(ditemukan)

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(seen_list[-MAX_STATE:], indent=2) + "\n", encoding="utf-8")

    if gagal == len(TARGETS):
        print("[ERROR] Semua sumber gagal diakses.")
        return 1

    if not nomor_baru:
        print("Radar Autopilot: 0 nomor baru yang lolos filter ketat.")
        return 0

    RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing_content = RULES_FILE.read_text(encoding="utf-8") if RULES_FILE.exists() else ""
    if existing_content and not existing_content.endswith("\n"):
        existing_content += "\n"

    baris_baru = "\n".join(nomor_ke_regex(n) for n in sorted(nomor_baru)) + "\n"
    RULES_FILE.write_text(existing_content + baris_baru, encoding="utf-8")
    print(f"[AUTOPILOT SUKSES] {len(nomor_baru)} nomor baru langsung ditambahkan ke {RULES_FILE}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

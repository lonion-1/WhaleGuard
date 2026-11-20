# Copyright (c) 2026 EazyWhale (https://github.com/lonion-1/WhaleGuard)
# SPDX-License-Identifier: AGPL-3.0-or-later
# Licensed under the GNU Affero General Public License v3.0.
"""WhaleGuard Unified Radar v7.0 (Full-Autopilot Multi-Source + Tight Proximity Filter).

Sumber pencarian:
1. Reddit Search JSON (r/indonesia, r/finansial, r/indotech, r/all).
2. Telegram Public Channel Web Preview (https://t.me/s/<channel>).
3. DuckDuckGo HTML Search (fallback lintas web non-JS).
"""
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REDDIT_TARGETS = [
    ("Reddit r/indonesia", "https://www.reddit.com/r/indonesia/search.json?q=penipu+OR+pinjol+OR+judol+OR+scam+OR+apk&restrict_sr=1&sort=new&t=month&limit=30"),
    ("Reddit r/finansial", "https://www.reddit.com/r/finansial/search.json?q=penipu+OR+pinjol+OR+phishing+OR+scam+OR+teror&restrict_sr=1&sort=new&t=month&limit=30"),
    ("Reddit r/indotech", "https://www.reddit.com/r/indotech/search.json?q=penipu+OR+spam+OR+phishing+OR+apk&restrict_sr=1&sort=new&t=month&limit=25"),
    ("Reddit Global ID", "https://www.reddit.com/search.json?q=%22nomor+penipu%22+OR+%22no+penipu%22+OR+%22undangan+apk%22&sort=new&t=month&limit=25"),
]

# Tambahkan username kanal Telegram publik info penipuan/pinjol di sini (tanpa '@')
TELEGRAM_CHANNELS = [
    "infopenipuan",
    "cekrekening",
    "korbanpinjol",
]

DDG_QUERIES = [
    ("DDG Nomor Penipu", '"nomor penipu" OR "no penipu" "08"'),
    ("DDG Pinjol Teror", '"teror pinjol" OR "dc pinjol" "08"'),
]

MAX_STATE = 3000
STATE_FILE = Path(".github/nomor_radar_seen.json")
RULES_FILE = Path("rules/numbers-spam-id.txt")
ALLOWLIST_FILE = Path("rules/numbers-allowlist.txt")

RE_PHONE = re.compile(r"(?<![\d+])(?:\+62|62|0)8[1-9](?:[ .\-]?\d){6,10}(?!\d)")
RE_EXISTING_RULE = re.compile(r"^\^?\(\\?\+62\|62\|0\)(8\d{8,11})\$?$")

# Kata kunci bukti kuat yang HARUS muncul dalam jarak ±55 karakter dari nomor telepon
RE_PROXIMITY_SCAM = re.compile(
    r"(?i)("
    r"\b(?:no|nomor|wa|whatsapp|tlp|telp)\s*(?:penipu|pelaku|dc|teror|dia|nya)\b|"
    r"\b(?:penipu|nipu|pelaku|scam\w*|salah\s*guna\w*|salahgunain|bajak|hack\w*)\b|"
    r"\b(?:pinjol|galbay|dc\b|debt\s*collector|teror\w*|ancam\w*|sebar\s*data|sebar\s*kontak)\b|"
    r"\b(?:judol|slot\s*gacor|phishing|smishing|malware|apk|undangan\s*apk)\b|"
    r"\b(?:akun\s*palsu|atas\s*nama|kronologi|viralkan|bantu\s*up)\b"
    r")"
)

# Tolak jika tepat di dekat nomor (±45 karakter) tercantum sebagai CS/kurir resmi
RE_OFFICIAL_CS_NOISE = re.compile(
    r"(?i)\b("
    r"call\s*center|cs\s*resmi|customer\s*service|layanan\s*pengaduan|"
    r"halo\s*bca|bri\s*call|mandiri\s*call|bni\s*call|no\s*resi|nomor\s*resi"
    r")\b"
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
        if not s or s.startswith("!"):
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


def http_get(url: str, user_agent: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[WARN] Gagal akses {url[:75]}: {e}")
        return None


def fetch_reddit(label: str, url: str) -> list[dict]:
    raw = http_get(url, "linux:whaleguard-radar:v7.0 (by /u/EazyWhale)")
    if not raw:
        return []
    try:
        data = json.loads(raw)
        children = data.get("data", {}).get("children", [])
    except Exception as e:
        print(f"[WARN] Gagal parse JSON {label}: {e}")
        return []

    hasil = []
    for item in children:
        d = item.get("data", {})
        pid = d.get("id")
        if not pid:
            continue
        hasil.append({
            "id": f"rd:{pid}",
            "source": label,
            "title": (d.get("title") or "").strip(),
            "text": (d.get("selftext") or "").strip(),
        })
    return hasil


def fetch_telegram_channel(channel: str) -> list[dict]:
    url = f"https://t.me/s/{channel}"
    raw = http_get(url, "Mozilla/5.0 (X11; Linux x86_64) WhaleGuard-Radar/7.0")
    if not raw:
        return []

    hasil = []
    blocks = re.findall(
        r'data-post="([^"]+)"[\s\S]*?<div class="tgme_widget_message_text[^"]*"[^>]*>([\s\S]*?)</div>',
        raw,
    )
    for post_id, msg_html in blocks:
        clean = bersihkan_html(msg_html)
        if clean:
            hasil.append({
                "id": f"tg:{post_id}",
                "source": f"Telegram @{channel}",
                "title": clean[:90],
                "text": clean,
            })
    return hasil


def fetch_ddg(label: str, query: str) -> list[dict]:
    encoded = urllib.parse.quote(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"
    raw = http_get(url, "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0")
    if not raw:
        return []

    hasil = []
    snippets = re.findall(r'<a class="result__snippet"[^>]*>([\s\S]*?)</a>', raw)
    for idx, snip_html in enumerate(snippets):
        clean = bersihkan_html(snip_html)
        if clean:
            hasil.append({
                "id": f"ddg:{hash(clean)}",
                "source": label,
                "title": clean[:90],
                "text": clean,
            })
    return hasil


def ekstrak_nomor_valid(teks: str, diabaikan: set[str]) -> set[str]:
    if RE_COMMERCIAL_NOISE.search(teks) and not RE_EXPLICIT_REPORT.search(teks):
        return set()

    lolos: set[str] = set()
    for m in RE_PHONE.finditer(teks):
        norm = normalisasi(m.group(0))
        if norm is None or norm in diabaikan:
            continue

        jendela_ketat = teks[max(0, m.start() - 45):min(len(teks), m.end() + 45)]
        if RE_OFFICIAL_CS_NOISE.search(jendela_ketat):
            continue

        jendela_konteks = teks[max(0, m.start() - 55):min(len(teks), m.end() + 55)]
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

    semua_post: list[dict] = []

    for label, url in REDDIT_TARGETS:
        semua_post.extend(fetch_reddit(label, url))
        time.sleep(1.5)

    for ch in TELEGRAM_CHANNELS:
        semua_post.extend(fetch_telegram_channel(ch))
        time.sleep(1.0)

    for label, q in DDG_QUERIES:
        semua_post.extend(fetch_ddg(label, q))
        time.sleep(3.0)

    nomor_baru: set[str] = set()
    for post in semua_post:
        sid = post["id"]
        if sid in seen:
            continue
        seen.add(sid)
        seen_list.append(sid)

        gabungan = f"{post['title']} | {post['text']}"
        ditemukan = ekstrak_nomor_valid(gabungan, diabaikan | nomor_baru)
        if ditemukan:
            print(f"[+{len(ditemukan)}] {post['source']}: {', '.join(sorted(ditemukan))} <- {post['title'][:80]}")
            nomor_baru.update(ditemukan)

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(seen_list[-MAX_STATE:], indent=2) + "\n", encoding="utf-8")

    if not nomor_baru:
        print("Radar Autopilot: 0 nomor baru yang lolos filter ketat.")
        return 0

    RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing_content = RULES_FILE.read_text(encoding="utf-8") if RULES_FILE.exists() else ""
    if existing_content and not existing_content.endswith("\n"):
        existing_content += "\n"

    baris_baru = "\n".join(nomor_ke_regex(n) for n in sorted(nomor_baru)) + "\n"
    RULES_FILE.write_text(existing_content + baris_baru, encoding="utf-8")
    print(f"[AUTOPILOT SUKSES] {len(nomor_baru)} nomor baru ditambahkan ke {RULES_FILE}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

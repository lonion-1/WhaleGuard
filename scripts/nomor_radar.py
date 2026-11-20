# Copyright (c) 2026 EazyWhale (https://github.com/lonion-1/WhaleGuard)
# SPDX-License-Identifier: AGPL-3.0-or-later
# Licensed under the GNU Affero General Public License v3.0.
"""WhaleGuard Unified Radar v8.1 (Auto-Discovery + Yield Evaluation & Auto-Rotation).

Fitur Otomatisasi Penuh:
1. Memindai kanal seed + kanal temuan (.github/discovered_channels.json) hingga 5 halaman ke belakang.
2. Snowball Discovery (tautan t.me/...) + Directory Indexing (lyzem.com).
3. Rapor Kinerja Kanal: melacak total nomor terpanen (harvested) & puasa hasil (dry_runs).
4. Auto-Rotation: kanal non-seed yang zonk 25x berturut-turut (dry_runs >= 25) atau mati 3x (misses >= 3)
   otomatis dipecat dan masuk daftar rejected agar slot selalu segar untuk kanal baru.
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

SEED_CHANNELS = [
    "rekampenipu",
    "cekrekening",
    "scamdetector_id",
]

DIRECTORY_QUERIES = [
    "https://lyzem.com/search?q=penipu",
    "https://lyzem.com/search?q=pinjol",
    "https://lyzem.com/search?q=scam+indonesia",
    "https://lyzem.com/search?q=blacklist+penipu",
]

MAX_STATE = 4000
MAX_ACTIVE_CHANNELS = 35
MAX_VERIFY_PER_RUN = 20
MAX_REJECTED = 800
MAX_DRY_RUNS = 25   # Pecat kanal non-seed jika 25x scan berturut-turut menghasilkan 0 nomor baru
MAX_MISSES = 3      # Pecat kanal non-seed jika 3x berturut-turut gagal diakses/kosong

STATE_FILE = Path(".github/nomor_radar_seen.json")
DISCOVERY_FILE = Path(".github/discovered_channels.json")
RULES_FILE = Path("rules/numbers-spam-id.txt")
ALLOWLIST_FILE = Path("rules/numbers-allowlist.txt")

RE_PHONE = re.compile(r"(?<![\d+])(?:\+62|62|0)8[1-9](?:[ .\-]?\d){6,10}(?!\d)")
RE_EXISTING_RULE = re.compile(r"^\^?\(\\?\+62\|62\|0\)([2-9]\d{7,11})\$?$")

# Hanya ambil tautan t.me/... agar tidak membuang kuota mengetes @username akun pribadi penipu
RE_TG_MENTION = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?([a-zA-Z][a-zA-Z0-9_]{4,31})\b"
)

RESERVED_TG_NAMES = {
    "joinchat", "addstickers", "addtheme", "setlanguage", "share", "proxy",
    "socks", "confirmphone", "iv", "login", "contact", "support", "telegram",
    "admin", "channel", "group", "botfather", "spaminfo", "cekrekening_bot",
}

RE_CHANNEL_RELEVANCE = re.compile(
    r"(?i)\b("
    r"penipu\w*|nipu|scam\w*|pinjol|galbay|debt\s*collector|teror\w*|"
    r"blacklist|cek\s*rekening|rekber|waspada|korban|lapor\w*|judol|phishing"
    r")\b"
)
RE_INDONESIAN_HINT = re.compile(
    r"(?i)\b(yang|dan|ini|itu|tidak|ada|korban|nomor|rekening|uang|rp|akun|waspada)\b"
)

RE_PROXIMITY_SCAM = re.compile(
    r"(?i)("
    r"\b(?:no|nomor|wa|whatsapp|tlp|telp)\s*(?:penipu|pelaku|dc|teror|dia|nya)\b|"
    r"\b(?:penipu|nipu|pelaku|scam\w*|salah\s*guna\w*|salahgunain|bajak|hack\w*)\b|"
    r"\b(?:pinjol|galbay|dc\b|debt\s*collector|teror\w*|ancam\w*|sebar\s*data|sebar\s*kontak)\b|"
    r"\b(?:judol|slot\s*gacor|phishing|smishing|malware|apk|undangan\s*apk)\b|"
    r"\b(?:akun\s*palsu|atas\s*nama|kronologi|viralkan|bantu\s*up)\b"
    r")"
)

RE_OFFICIAL_CS_NOISE = re.compile(
    r"(?i)\b("
    r"call\s*center|cs\s*resmi|customer\s*service|layanan\s*pengaduan|"
    r"halo\s*bca|bri\s*call|mandiri\s*call|bni\s*call|no\s*resi|nomor\s*resi"
    r")\b"
)

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


def default_meta(source: str) -> dict:
    return {
        "source": source,
        "scans": 0,
        "harvested": 0,
        "dry_runs": 0,
        "misses": 0,
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


def http_get(url: str) -> str | None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
            "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[WARN] Gagal akses {url[:75]}: {e}")
        return None


def muat_discovery_state() -> dict:
    channels = {ch: default_meta("seed") for ch in SEED_CHANNELS}
    if not DISCOVERY_FILE.exists():
        return {"channels": channels, "rejected": []}
    try:
        data = json.loads(DISCOVERY_FILE.read_text(encoding="utf-8"))
        saved = data.get("channels", {})
        for ch, raw_meta in saved.items():
            m = default_meta(raw_meta.get("source", "auto"))
            m["scans"] = int(raw_meta.get("scans", 0))
            m["harvested"] = int(raw_meta.get("harvested", 0))
            m["dry_runs"] = int(raw_meta.get("dry_runs", 0))
            m["misses"] = int(raw_meta.get("misses", 0))
            channels[ch] = m
        for ch in SEED_CHANNELS:
            channels.setdefault(ch, default_meta("seed"))
        return {
            "channels": channels,
            "rejected": list(data.get("rejected", []))[-MAX_REJECTED:],
        }
    except Exception:
        return {"channels": channels, "rejected": []}


def simpan_discovery_state(state: dict) -> None:
    DISCOVERY_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Urutkan kanal: seed di atas, lalu berdasarkan jumlah panen terbanyak
    sorted_channels = dict(
        sorted(
            state["channels"].items(),
            key=lambda kv: (kv[0] in SEED_CHANNELS, kv[1].get("harvested", 0)),
            reverse=True,
        )
    )
    state["channels"] = sorted_channels
    state["rejected"] = list(dict.fromkeys(state["rejected"]))[-MAX_REJECTED:]
    DISCOVERY_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ekstrak_kandidat_username(teks: str) -> set[str]:
    kandidat: set[str] = set()
    for m in RE_TG_MENTION.finditer(teks):
        uname = m.group(1)
        low = uname.lower()
        if low in RESERVED_TG_NAMES or low.endswith("bot"):
            continue
        kandidat.add(uname)
    return kandidat


def verifikasi_kanal_publik(username: str) -> bool:
    url = f"https://t.me/s/{username}"
    raw = http_get(url)
    if not raw or "tgme_widget_message_text" not in raw:
        return False

    title_m = re.search(r'class="tgme_channel_info_header_title"[^>]*>([\s\S]*?)</div>', raw)
    desc_m = re.search(r'class="tgme_channel_info_description"[^>]*>([\s\S]*?)</div>', raw)
    msgs = re.findall(r'<div class="tgme_widget_message_text[^"]*"[^>]*>([\s\S]*?)</div>', raw)

    if len(msgs) < 3:
        return False

    sampel_teks = " ".join([
        bersihkan_html(title_m.group(1)) if title_m else "",
        bersihkan_html(desc_m.group(1)) if desc_m else "",
        *[bersihkan_html(x) for x in msgs[-10:]],
    ])

    has_topic = bool(RE_CHANNEL_RELEVANCE.search(sampel_teks))
    has_id_lang = len(RE_INDONESIAN_HINT.findall(sampel_teks)) >= 3
    return has_topic and has_id_lang


def fetch_directory_candidates() -> set[str]:
    kandidat: set[str] = set()
    for url in DIRECTORY_QUERIES:
        raw = http_get(url)
        if raw:
            found = ekstrak_kandidat_username(raw)
            print(f"[DISCOVERY] Direktori {url.split('=')[-1]}: {len(found)} kandidat mentah")
            kandidat.update(found)
        time.sleep(1.5)
    return kandidat


def fetch_telegram_channel(channel: str, max_pages: int = 5) -> list[dict]:
    hasil = []
    seen_local: set[str] = set()
    before_id: str | None = None

    for _ in range(max_pages):
        url = f"https://t.me/s/{channel}" + (f"?before={before_id}" if before_id else "")
        raw = http_get(url)
        if not raw:
            break

        blocks = re.findall(
            r'data-post="([^"]+)"[\s\S]*?<div class="tgme_widget_message_text[^"]*"[^>]*>([\s\S]*?)</div>',
            raw,
        )
        if not blocks:
            break

        for post_id, msg_html in blocks:
            if post_id in seen_local:
                continue
            seen_local.add(post_id)
            clean = bersihkan_html(msg_html)
            if clean:
                hasil.append({
                    "id": f"tg:{post_id}",
                    "channel": channel,
                    "source": f"Telegram @{channel}",
                    "title": clean[:90],
                    "text": clean,
                })

        first_post = blocks[0][0]
        if "/" not in first_post:
            break
        oldest_num = first_post.split("/")[-1]
        if not oldest_num.isdigit() or oldest_num == before_id or int(oldest_num) <= 1:
            break
        before_id = oldest_num
        time.sleep(1.0)

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

    discovery = muat_discovery_state()
    channels_map: dict = discovery["channels"]
    rejected_set: set[str] = {x.lower() for x in discovery["rejected"]}
    known_lower: set[str] = {k.lower() for k in channels_map}

    snowball_candidates: set[str] = set()
    nomor_baru: set[str] = set()
    channels_to_prune: list[tuple[str, str]] = []

    # 1. Pindai & nilai produktivitas setiap kanal
    for ch, meta in list(channels_map.items()):
        items = fetch_telegram_channel(ch, max_pages=5)
        meta["scans"] += 1

        if not items:
            meta["misses"] += 1
            print(f"[INFO] Telegram @{ch} ({meta['source']}): 0 pesan (miss {meta['misses']}/{MAX_MISSES})")
            if ch not in SEED_CHANNELS and meta["misses"] >= MAX_MISSES:
                channels_to_prune.append((ch, "mati/kosong"))
            time.sleep(1.0)
            continue

        meta["misses"] = 0
        panen_kanal_ini = 0

        for post in items:
            gabungan = f"{post['title']} | {post['text']}"
            if RE_CHANNEL_RELEVANCE.search(gabungan):
                snowball_candidates.update(ekstrak_kandidat_username(gabungan))

            sid = post["id"]
            if sid in seen:
                continue
            seen.add(sid)
            seen_list.append(sid)

            ditemukan = ekstrak_nomor_valid(gabungan, diabaikan | nomor_baru)
            if ditemukan:
                print(f"[+{len(ditemukan)}] {post['source']}: {', '.join(sorted(ditemukan))} <- {post['title'][:70]}")
                nomor_baru.update(ditemukan)
                panen_kanal_ini += len(ditemukan)

        if panen_kanal_ini > 0:
            meta["harvested"] += panen_kanal_ini
            meta["dry_runs"] = 0
        else:
            meta["dry_runs"] += 1

        print(
            f"[INFO] Telegram @{ch} ({meta['source']}): {len(items)} pesan | "
            f"+{panen_kanal_ini} nomor (total: {meta['harvested']}, zonk: {meta['dry_runs']}/{MAX_DRY_RUNS})"
        )

        if ch not in SEED_CHANNELS and meta["dry_runs"] >= MAX_DRY_RUNS:
            channels_to_prune.append((ch, f"zonk {MAX_DRY_RUNS}x berturut-turut"))

        time.sleep(1.0)

    # 2. Pecat kanal mati atau tidak produktif -> pindahkan ke rejected agar slot terbuka
    for ch, alasan in channels_to_prune:
        print(f"[ROTATE] Memecat @{ch} ({alasan}) -> buka slot baru")
        channels_map.pop(ch, None)
        known_lower.discard(ch.lower())
        discovery["rejected"].append(ch)
        rejected_set.add(ch.lower())

    # 3. Auto-Discovery kanal baru untuk mengisi slot yang kosong
    if len(channels_map) < MAX_ACTIVE_CHANNELS:
        dir_candidates = fetch_directory_candidates()
        prioritas_dir = [
            u for u in dir_candidates
            if u.lower() not in known_lower and u.lower() not in rejected_set
        ]
        prioritas_snowball = [
            u for u in snowball_candidates
            if u.lower() not in known_lower and u.lower() not in rejected_set and u not in prioritas_dir
        ]
        kandidat_baru = prioritas_dir + prioritas_snowball

        verified_count = 0
        for cand in kandidat_baru[:MAX_VERIFY_PER_RUN]:
            if len(channels_map) >= MAX_ACTIVE_CHANNELS:
                break
            src = "directory" if cand in prioritas_dir else "snowball"
            if verifikasi_kanal_publik(cand):
                channels_map[cand] = default_meta(src)
                known_lower.add(cand.lower())
                verified_count += 1
                print(f"[NEW CHANNEL] Kanal baru terverifikasi ({src}): @{cand}")
            else:
                discovery["rejected"].append(cand)
                rejected_set.add(cand.lower())
            time.sleep(1.2)

        if verified_count:
            print(f"[DISCOVERY SUKSES] {verified_count} kanal baru ditambahkan ke daftar pantau.")

    simpan_discovery_state(discovery)

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

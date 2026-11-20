# Copyright (c) 2026 <EazyWhale>
# Licensed under the MIT License.
"""WhaleGuard Auto-Harvester: sedot nomor spam mentah -> regex rules/numbers-spam-id.txt.

Sumber otomatis:
1. File lokal inbox/raw_numbers.txt (tempel teks/nomor apa pun di sini, bot akan memproses & membersihkannya).
2. Daftar URL raw teks/CSV publik di FEED_URLS.
"""
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Opsional: masukkan URL raw daftar nomor spam publik (.txt / .csv) jika ada
FEED_URLS: list[str] = [
    # "https://raw.githubusercontent.com/contoh-user/contoh-repo/main/spam-numbers.txt",
]

INBOX_FILE = Path("inbox/raw_numbers.txt")
RULES_FILE = Path("rules/numbers-spam-id.txt")

RE_PHONE = re.compile(r"(?<![\d+])(?:\+62|62|0)8[1-9](?:[ .\-]?\d){6,10}(?!\d)")
RE_EXISTING_RULE = re.compile(r"^\^?\(\\?\+62\|62\|0\)(8\d{8,11})\$?$")

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
    subscriber = norm_08[1:]  # buang '0' depan -> '8123456789'
    return rf"^(\+62|62|0){subscriber}$"


def muat_nomor_eksisting(path: Path) -> set[str]:
    sudah_ada: set[str] = set()
    if not path.exists():
        return sudah_ada
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = RE_EXISTING_RULE.match(s)
        if m:
            sudah_ada.add("0" + m.group(1))
        elif (norm := normalisasi(s)) is not None:
            sudah_ada.add(norm)
    return sudah_ada


def fetch_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; WhaleGuard-Harvester/1.0)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[WARN] Gagal mengambil feed {url}: {e}")
        return ""


def main() -> int:
    kumpulan_teks: list[str] = []

    if INBOX_FILE.exists():
        isi_inbox = INBOX_FILE.read_text(encoding="utf-8")
        if isi_inbox.strip():
            print("[OK] Membaca nomor dari inbox/raw_numbers.txt...")
            kumpulan_teks.append(isi_inbox)

    for url in FEED_URLS:
        u = url.strip()
        if u:
            teks_feed = fetch_text(u)
            if teks_feed:
                print(f"[OK] Membaca feed dari {u}")
                kumpulan_teks.append(teks_feed)

    if not kumpulan_teks:
        print("Auto-Harvester: inbox kosong & tidak ada FEED_URLS aktif.")
        return 0

    gabungan = "\n".join(kumpulan_teks)
    kandidat = {
        n for m in RE_PHONE.finditer(gabungan)
        if (n := normalisasi(m.group(0))) is not None
    }

    sudah_ada = muat_nomor_eksisting(RULES_FILE)
    nomor_baru = sorted(kandidat - sudah_ada)

    if nomor_baru:
        RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
        existing_content = RULES_FILE.read_text(encoding="utf-8") if RULES_FILE.exists() else ""
        if existing_content and not existing_content.endswith("\n"):
            existing_content += "\n"

        baris_baru = "\n".join(nomor_ke_regex(n) for n in nomor_baru) + "\n"
        RULES_FILE.write_text(existing_content + baris_baru, encoding="utf-8")
        print(f"[SUKSES] Menambahkan {len(nomor_baru)} nomor baru ke {RULES_FILE}.")
    else:
        print("[INFO] Tidak ada nomor baru (semua sudah ada di daftar).")

    # Kosongkan inbox setelah diproses agar tidak diproses ulang
    if INBOX_FILE.exists() and INBOX_FILE.read_text(encoding="utf-8").strip():
        INBOX_FILE.write_text(
            "# Tempel nomor penipu mentah (08xx / +628xx) atau teks laporan di bawah ini.\n"
            "# Bot Auto-Harvester akan otomatis mengubahnya jadi Regex di rules/numbers-spam-id.txt.\n",
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())

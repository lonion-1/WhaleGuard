# Copyright (c) 2026 EazyWhale (https://github.com/lonion-1/WhaleGuard)
# SPDX-License-Identifier: AGPL-3.0-or-later
# Licensed under the GNU Affero General Public License v3.0.
"""WhaleGuard Auto-Harvester: sedot nomor spam mentah (HP & Telepon Rumah/VoIP) -> regex rules/numbers-spam-id.txt."""
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

FEED_URLS: list[str] = [
    # Tambahkan URL raw GitHub / Gist komunitas di sini:
    # "https://raw.githubusercontent.com/contoh-user/contoh-repo/main/spam-numbers.txt",
]

INBOX_FILE = Path("inbox/raw_numbers.txt")
RULES_FILE = Path("rules/numbers-spam-id.txt")
ALLOWLIST_FILE = Path("rules/numbers-allowlist.txt")

# Mendukung nomor HP (08xx) maupun nomor kantor/VoIP (021xx, 022xx, dst.)
RE_PHONE = re.compile(r"(?<![\d+])(?:\+62|62|0)[2-9](?:[ .\-]?\d){7,11}(?!\d)")
RE_EXISTING_RULE = re.compile(r"^\^?\(\\?\+62\|62\|0\)([2-9]\d{7,11})\$?$")

DUMMY_NUMBERS = {
    "0812345678", "08123456789", "081234567890", "0812345678901",
    "08987654321", "081122334455",
}


def normalisasi(nomor: str) -> str | None:
    d = re.sub(r"\D", "", nomor)
    if d.startswith("62"):
        d = "0" + d[2:]
    if not re.fullmatch(r"0[2-9]\d{7,11}", d):
        return None
    if d in DUMMY_NUMBERS or len(set(d[2:])) == 1:
        return None
    return d


def nomor_ke_regex(norm_0: str) -> str:
    return rf"^(\+62|62|0){norm_0[1:]}$"


def muat_allowlist(path: Path) -> set[str]:
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


def bersihkan_dan_muat_rules(path: Path, allowlist: set[str]) -> set[str]:
    sudah_ada: set[str] = set()
    if not path.exists():
        return sudah_ada

    lines_bersih: list[str] = []
    terhapus = 0

    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith(("#", "!")):
            lines_bersih.append(line)
            continue

        m = RE_EXISTING_RULE.match(s)
        norm = ("0" + m.group(1)) if m else normalisasi(s)

        if norm is not None and norm in allowlist:
            terhapus += 1
            continue

        if norm is not None:
            sudah_ada.add(norm)
        lines_bersih.append(line)

    if terhapus > 0:
        path.write_text("\n".join(lines_bersih) + "\n", encoding="utf-8")
        print(f"[ALLOWLIST] Menghapus {terhapus} nomor dari {path} karena terdaftar di allowlist.")

    return sudah_ada


def fetch_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; WhaleGuard-Harvester/2.1)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[WARN] Gagal mengambil feed {url}: {e}")
        return ""


def main() -> int:
    allowlist = muat_allowlist(ALLOWLIST_FILE)
    sudah_ada = bersihkan_dan_muat_rules(RULES_FILE, allowlist)

    kumpulan_teks: list[str] = []
    inbox_ada_isi = False

    if INBOX_FILE.exists():
        isi_inbox = INBOX_FILE.read_text(encoding="utf-8")
        baris_aktif = [b for b in isi_inbox.splitlines() if b.strip() and not b.strip().startswith(("#", "!"))]
        if baris_aktif:
            inbox_ada_isi = True
            print("[OK] Membaca nomor dari inbox/raw_numbers.txt...")
            kumpulan_teks.append("\n".join(baris_aktif))

    for url in FEED_URLS:
        u = url.strip()
        if u:
            teks_feed = fetch_text(u)
            if teks_feed:
                print(f"[OK] Membaca feed dari {u}")
                kumpulan_teks.append(teks_feed)

    if kumpulan_teks:
        gabungan = "\n".join(kumpulan_teks)
        kandidat = {
            n for m in RE_PHONE.finditer(gabungan)
            if (n := normalisasi(m.group(0))) is not None
        }

        diblokir_allowlist = kandidat & allowlist
        if diblokir_allowlist:
            print(f"[ALLOWLIST] Melewati {len(diblokir_allowlist)} nomor karena dilindungi allowlist.")

        nomor_baru = sorted(kandidat - sudah_ada - allowlist)

        if nomor_baru:
            RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
            existing_content = RULES_FILE.read_text(encoding="utf-8") if RULES_FILE.exists() else ""
            if existing_content and not existing_content.endswith("\n"):
                existing_content += "\n"

            baris_baru = "\n".join(nomor_ke_regex(n) for n in nomor_baru) + "\n"
            RULES_FILE.write_text(existing_content + baris_baru, encoding="utf-8")
            print(f"[SUKSES] Menambahkan {len(nomor_baru)} nomor baru ke {RULES_FILE}.")
        else:
            print("[INFO] Tidak ada nomor baru (semua sudah tercatat atau masuk allowlist).")

    if inbox_ada_isi:
        INBOX_FILE.write_text(
            "# Tempel nomor penipu mentah (08xx / 021xx / +62xx) atau teks laporan di bawah ini.\n"
            "# Bot Auto-Harvester akan otomatis mengubahnya jadi Regex di rules/numbers-spam-id.txt.\n",
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())

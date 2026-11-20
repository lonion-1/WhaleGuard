# Copyright (c) 2026 EazyWhale (https://github.com/lonion-1/WhaleGuard)
# SPDX-License-Identifier: AGPL-3.0-or-later
# Licensed under the GNU Affero General Public License v3.0.

import datetime
import os
import re
import sys
from pathlib import Path

NOW_UTC = datetime.datetime.now(datetime.timezone.utc)
WAKTU = NOW_UTC.strftime("%Y.%m.%d.%H%M")

SMS_BLOCK_FILES = {
    "rules/sms-judol-id.txt": "WhaleGuard - Filter SMS Judi Online (Indonesia)",
    "rules/sms-scam-pinjol-id.txt": "WhaleGuard - Filter SMS Penipuan, Malware .APK & Pinjol Ilegal",
}
SMS_ALLOW_FILE = ("rules/sms-allowlist-otp.txt", "WhaleGuard - Pengecualian SMS OTP, Perbankan & Kurir Resmi")
NUMBER_BLOCK_FILE = ("rules/numbers-spam-id.txt", "WhaleGuard - Daftar Nomor Spam & Penipu Terverifikasi (Indonesia)")
NUMBER_ALLOW_FILE = Path("rules/numbers-allowlist.txt")
PLAIN_NUMBER_FILE = "rules/numbers-spam-id-plain.txt"

SAFE_SMS_SAMPLES = [
    "Kode OTP Anda adalah 849201. JANGAN BERIKAN kode ini kepada siapapun termasuk pihak bank.",
    "BCA: Transaksi berhasil Rp 250.000 pada 20/11/2026. Info hubungi Halo BCA 1500888.",
    "Paket J&T dengan no resi JP1234567890 sedang diantar oleh kurir ke alamat Anda.",
    "Your WhatsApp code: 551-902. Don't share this code with others.",
    "Gunakan kode verifikasi 991204 untuk masuk ke akun Google Anda.",
    "Tagihan listrik PLN bulan ini Rp 350.000 telah lunas terbayar.",
    "BRI: Pembayaran QRIS sebesar Rp 45.000 berhasil.",
]

SPAM_SMS_SAMPLES = [
    "Info slot gacor hari ini maxwin zeus x500 deposit pulsa tanpa potongan!",
    "Undangan pernikahan digital silakan buka file Undangan_Resmi.apk",
    "Pinjaman online dana tunai cepat limit pinjaman anda disetujui tanpa agunan!",
]

SAFE_NUMBERS = [
    "110", "112", "113", "118", "119",
    "1500888", "0211500888", "+62211500888",
    "14000", "02114000", "+622114000",
    "1500017", "14041", "188",
]

HEADER_PREFIXES = (
    "! Title:",
    "! Copyright",
    "! License:",
    "! Maintainer:",
    "! Version:",
    "! Total Rules:",
    "! --------------------------------------------------",
)

RE_EXISTING_RULE = re.compile(r"^\^?\(\\?\+62\|62\|0\)([2-9][0-9]{6,11})\$?$")


def normalisasi_nomor_id(raw: str) -> str:
    """Ubah nomor telepon Indonesia polos menjadi regex universal (+62/62/0)."""
    s = raw.strip()
    bersih = re.sub(r"[\s\-().]", "", s)
    if re.fullmatch(r"(?:\+?62|62|0)8[1-9][0-9]{6,11}", bersih):
        inti = re.sub(r"^(?:\+?62|62|0)", "", bersih)
        return rf"^(\+62|62|0){inti}$"
    if re.fullmatch(r"(?:\+?62|62|0)[2-9][0-9]{7,10}", bersih):
        inti = re.sub(r"^(?:\+?62|62|0)", "", bersih)
        return rf"^(\+62|62|0){inti}$"
    return s


def muat_allowlist_regex() -> set[str]:
    """Kumpulkan semua nomor di rules/numbers-allowlist.txt dalam bentuk regex baku."""
    allowed_regexes: set[str] = set()
    if not NUMBER_ALLOW_FILE.exists():
        return allowed_regexes
    for line in NUMBER_ALLOW_FILE.read_text(encoding="utf-8").splitlines():
        s = line.split("#", 1)[0].strip()
        if not s or s.startswith("!"):
            continue
        allowed_regexes.add(normalisasi_nomor_id(s))
    return allowed_regexes


def fmt_angka(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def tulis_file(path: Path, title: str, rules: list[str]) -> bool:
    header = [
        f"! Title: {title}",
        "! Copyright (c) 2026 <EazyWhale>",
        "! License: GNU General Public License v3.0 (GPL-3.0)",
        "! Maintainer: EazyWhale",
        f"! Version: {WAKTU}",
        f"! Total Rules: {len(rules)}",
        "! --------------------------------------------------",
        "",
    ]
    isi_baru = "\n".join(header + rules) + "\n"
    if path.exists():
        lama_rules = [
            l.strip() for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.strip().startswith("!")
        ]
        if lama_rules == rules:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(isi_baru, encoding="utf-8", newline="\n")
    return True


def proses_sms_file(file_str: str, title: str, is_allowlist: bool, summary: list[str]):
    path = Path(file_str)
    if not path.exists():
        summary.append(f"- **{file_str}**: File tidak ditemukan, dilewati.")
        return 0

    unik = []
    seen = set()
    duplikat = 0

    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith(HEADER_PREFIXES) or s.startswith(("!", "#")):
            continue

        try:
            rx = re.compile(s)
        except re.error as err:
            sys.exit(f"GAGAL di {file_str} baris {no}: Regex tidak valid ({err}) -> {s}")

        if rx.search("") is not None:
            sys.exit(f"GAGAL di {file_str} baris {no}: Regex terlalu luas (cocok dengan teks kosong) -> {s}")

        if not is_allowlist:
            for sample in SAFE_SMS_SAMPLES:
                if rx.search(sample):
                    sys.exit(
                        f"GAGAL (False Positive) di {file_str} baris {no}!\n"
                        f"  Aturan : {s}\n"
                        f"  Menabrak SMS sah: \"{sample}\""
                    )
        else:
            for spam in SPAM_SMS_SAMPLES:
                if rx.search(spam):
                    sys.exit(
                        f"GAGAL (Allowlist Bocor) di {file_str} baris {no}!\n"
                        f"  Aturan : {s}\n"
                        f"  Meloloskan SMS spam: \"{spam}\""
                    )

        if s in seen:
            duplikat += 1
            continue
        seen.add(s)
        unik.append(s)

    unik.sort()
    tulis_file(path, title, unik)
    summary.append(f"- **{file_str}**: **{len(unik)}** pola regex aktif ({duplikat} duplikat dibersihkan)")
    return len(unik)


def proses_number_file(file_str: str, title: str, summary: list[str]):
    path = Path(file_str)
    if not path.exists():
        summary.append(f"- **{file_str}**: File tidak ditemukan, dilewati.")
        return 0

    allowlist_rx = muat_allowlist_regex()
    unik = []
    seen = set()
    duplikat = 0
    dihapus_allowlist = 0

    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith(HEADER_PREFIXES) or s.startswith(("!", "#")):
            continue

        norm = normalisasi_nomor_id(s)

        if norm in allowlist_rx:
            dihapus_allowlist += 1
            continue

        try:
            rx = re.compile(norm)
        except re.error as err:
            sys.exit(f"GAGAL di {file_str} baris {no}: Pola nomor tidak valid ({err}) -> {s}")

        if rx.search("") is not None:
            sys.exit(f"GAGAL di {file_str} baris {no}: Pola nomor terlalu luas -> {s}")

        for safe_num in SAFE_NUMBERS:
            if rx.search(safe_num):
                sys.exit(
                    f"GAGAL (Nomor Darurat/Resmi Dilindungi) di {file_str} baris {no}!\n"
                    f"  Aturan : {norm}\n"
                    f"  Menabrak nomor penting: {safe_num}"
                )

        if norm in seen:
            duplikat += 1
            continue
        seen.add(norm)
        unik.append(norm)

    unik.sort()
    tulis_file(path, title, unik)
    info_allow = f", {dihapus_allowlist} dihapus via allowlist" if dihapus_allowlist else ""
    summary.append(f"- **{file_str}**: **{len(unik)}** aturan nomor aktif ({duplikat} duplikat dibersihkan{info_allow})")
    return len(unik)


def tulis_plain_numbers(regex_rules: list[str], summary: list[str]) -> int:
    """Ekspor daftar nomor spam ke format internasional polos (+62...) untuk iOS & dialer umum."""
    plain_path = Path(PLAIN_NUMBER_FILE)
    plain_numbers: list[str] = []

    for r in regex_rules:
        m = RE_EXISTING_RULE.match(r)
        if m:
            plain_numbers.append("+62" + m.group(1))

    plain_numbers.sort()
    tulis_file(
        plain_path,
        "WhaleGuard - Daftar Nomor Spam Polos (+62) untuk iOS & Dialer Umum",
        plain_numbers,
    )
    summary.append(f"- **{plain_path.as_posix()}**: **{len(plain_numbers)}** nomor polos aktif (iOS/Universal)")
    return len(plain_numbers)


def update_readme(counts: dict[str, int]):
    readme_path = Path("README.md")
    if not readme_path.exists():
        return
    teks_awal = readme_path.read_text(encoding="utf-8")
    teks_baru = teks_awal
    for fname, jml in counts.items():
        pola = rf"(<!-- COUNT:{re.escape(fname)} -->).*?(<!-- /COUNT -->)"
        teks_baru = re.sub(pola, lambda m: m.group(1) + fmt_angka(jml) + m.group(2), teks_baru)
    if teks_baru != teks_awal:
        readme_path.write_text(teks_baru, encoding="utf-8")


def main():
    summary = ["### 🛡️ Ringkasan Validasi & Pembaruan WhaleGuard\n"]
    counts = {}

    for f_path, title in SMS_BLOCK_FILES.items():
        counts[f_path] = proses_sms_file(f_path, title, is_allowlist=False, summary=summary)

    allow_path, allow_title = SMS_ALLOW_FILE
    counts[allow_path] = proses_sms_file(allow_path, allow_title, is_allowlist=True, summary=summary)

    num_path, num_title = NUMBER_BLOCK_FILE
    counts[num_path] = proses_number_file(num_path, num_title, summary=summary)

    # Auto-generate versi polos (+62...) untuk iOS & dialer umum
    regex_aktif = [
        l.strip() for l in Path(num_path).read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.strip().startswith("!")
    ]
    counts[PLAIN_NUMBER_FILE] = tulis_plain_numbers(regex_aktif, summary)

    update_readme(counts)
    Path("last-run.txt").write_text(f"Last check (UTC): {WAKTU}\n", encoding="utf-8")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as sf:
            sf.write("\n".join(summary) + "\n")

    print("\n".join(summary))


if __name__ == "__main__":
    main()

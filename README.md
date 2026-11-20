<div align="center">

# 🛡️ WhaleGuard — Benteng Privasi Telepon & SMS
**Kumpulan aturan Regex dan daftar blokir nomor spam terkurasi otomatis khusus Indonesia untuk aplikasi pemblokir panggilan & SMS berbasis lokal (*on-device*) di Android maupun iOS.**

[![Radar Autopilot](https://img.shields.io/github/actions/workflow/status/lonion-1/WhaleGuard/nomor-radar.yml?branch=main&label=Radar%20Autopilot&style=flat)](https://github.com/lonion-1/WhaleGuard/actions/workflows/nomor-radar.yml) [![Auto-Harvester](https://img.shields.io/github/actions/workflow/status/lonion-1/WhaleGuard/auto-harvest.yml?branch=main&label=Auto-Harvester&style=flat)](https://github.com/lonion-1/WhaleGuard/actions/workflows/auto-harvest.yml) [![Last Commit](https://img.shields.io/github/last-commit/lonion-1/WhaleGuard?label=Last%20Update&style=flat&color=success)](https://github.com/lonion-1/WhaleGuard/commits/main)
![Privacy](https://img.shields.io/badge/Privacy-100%25%20On--Device-blue?style=flat)
![Platform](https://img.shields.io/badge/Platform-Android%20%26%20iOS-success?style=flat)

</div>

---

## ✨ Mengapa WhaleGuard?

* **100% Lokal & Privat (*On-Device*):** Semua pencocokan nomor dan teks SMS berjalan langsung di dalam perangkatmu tanpa pernah mengunggah buku kontak maupun riwayat panggilan ke server pihak ketiga.
* **Perlindungan OTP & Kurir Otomatis:** Setiap aturan diuji melalui simulator CI anti-*false positive* agar tidak pernah memblokir kode OTP bank, mutasi rekening, nomor darurat, maupun notifikasi kurir resmi.
* **Radar & Panen Otomatis (*Autopilot*):** Memindai laporan nomor penipu dan teror pinjol secara berkala, membersihkan duplikat, dan langsung menyusunnya ke format Regex universal (`+62` / `62` / `0`) serta format nomor polos (`+62`).
* **Allowlist Berbasis Komunitas:** Nomor resmi atau layanan pelanggan yang tidak sengaja masuk daftar blokir dapat segera dipulihkan dan dilindungi permanen melalui laporan komunitas.

---

## 📦 Daftar Tautan Aturan (*Raw URLs*)

| Kategori | Format & Target | File | Aturan Aktif | Last Update | Raw URL (Salin ke Aplikasi) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **SMS Judi Online** | Regex (Android) | `rules/sms-judol-id.txt` | <!-- COUNT:rules/sms-judol-id.txt -->5<!-- /COUNT --> | ![Judol Update](https://img.shields.io/github/last-commit/lonion-1/WhaleGuard?path=rules%2Fsms-judol-id.txt&label=Updated&style=flat) | `https://raw.githubusercontent.com/lonion-1/WhaleGuard/main/rules/sms-judol-id.txt` |
| **SMS Penipuan, Pinjol & `.apk`** | Regex (Android) | `rules/sms-scam-pinjol-id.txt` | <!-- COUNT:rules/sms-scam-pinjol-id.txt -->7<!-- /COUNT --> | ![Scam Update](https://img.shields.io/github/last-commit/lonion-1/WhaleGuard?path=rules%2Fsms-scam-pinjol-id.txt&label=Updated&style=flat) | `https://raw.githubusercontent.com/lonion-1/WhaleGuard/main/rules/sms-scam-pinjol-id.txt` |
| **Allowlist OTP & Kurir (Penting)** | Regex Whitelist (Android) | `rules/sms-allowlist-otp.txt` | <!-- COUNT:rules/sms-allowlist-otp.txt -->3<!-- /COUNT --> | ![OTP Update](https://img.shields.io/github/last-commit/lonion-1/WhaleGuard?path=rules%2Fsms-allowlist-otp.txt&label=Updated&style=flat) | `https://raw.githubusercontent.com/lonion-1/WhaleGuard/main/rules/sms-allowlist-otp.txt` |
| **Nomor Spam & Penipu (Regex)** | Regex `^(\+62\|62\|0)...$` (Android) | `rules/numbers-spam-id.txt` | <!-- COUNT:rules/numbers-spam-id.txt -->58<!-- /COUNT --> | ![Numbers Update](https://img.shields.io/github/last-commit/lonion-1/WhaleGuard?path=rules%2Fnumbers-spam-id.txt&label=Updated&style=flat) | `https://raw.githubusercontent.com/lonion-1/WhaleGuard/main/rules/numbers-spam-id.txt` |
| **Nomor Spam & Penipu (Polos)** | Nomor `+62...` (iOS & Dialer Umum) | `rules/numbers-spam-id-plain.txt` | <!-- COUNT:rules/numbers-spam-id-plain.txt -->58<!-- /COUNT --> | ![Plain Update](https://img.shields.io/github/last-commit/lonion-1/WhaleGuard?path=rules%2Fnumbers-spam-id-plain.txt&label=Updated&style=flat) | `https://raw.githubusercontent.com/lonion-1/WhaleGuard/main/rules/numbers-spam-id-plain.txt` |

---

## 📱 Panduan Pemasangan

### 1. Android — SpamBlocker (Rekomendasi Utama)
1. Unduh dan pasang aplikasi **SpamBlocker** melalui **[F-Droid](https://f-droid.org/packages/spam.blocker/)** atau halaman **[GitHub Releases](https://github.com/aj3423/SpamBlocker/releases)**.
2. Buka tab **Automations / Workflows** di dalam aplikasi SpamBlocker untuk menarik daftar secara berkala dari URL *Raw* di atas:
   * Gunakan tindakan **HTTP Request** menuju tautan *Raw* di atas $\rightarrow$ sambungkan ke **Regex Parse** (pisahkan per baris, abaikan baris berawalan `!`) $\rightarrow$ **Import to SMS/Number Rules**.
   * Pastikan aturan dari **`rules/sms-allowlist-otp.txt`** diimpor sebagai **Allow (Whitelist)** agar kode OTP selalu lolos.
3. Aktifkan opsi **Repeated Call** (misal: izinkan jika nomor yang sama menelepon 2x dalam 5 menit) agar panggilan darurat atau kurir paket tetap dapat terhubung.

### 2. iOS & Aplikasi Pemblokir Non-Regex
* Gunakan tautan **`rules/numbers-spam-id-plain.txt`** yang berisi daftar nomor standar internasional (`+62...`) tanpa simbol regex (abaikan baris komentar berawalan `!`).
* Daftar ini dapat diimpor ke aplikasi pemblokir panggilan lokal berbasis **CallKit** di iOS (seperti *Call Ranger* atau *WideProtect*) maupun fitur impor daftar blokir pada aplikasi telepon lainnya.

---

## 🤝 Kontribusi Komunitas (Lapor Spam & Salah Blokir)

Sistem **WhaleGuard** terhubung langsung dengan otomatisasi GitHub Issues sehingga laporanmu dapat diproses dengan cepat:

* **🚨 Lapor Nomor Penipu atau SMS Judol Baru:**
  Buka **[Form Lapor Nomor Spam & SMS](https://github.com/lonion-1/WhaleGuard/issues/new?template=lapor-spam.yml)**. Laporan nomor telepon valid akan langsung diproses otomatis ke daftar blokir, sementara contoh SMS baru akan diperiksa terhadap pola Regex aktif.
* **🛡️ Lapor Salah Blokir (*Community Allowlist*):**
  Menemukan nomor kurir, layanan pelanggan resmi, atau nomor pribadi yang tidak sengaja ikut terblokir? Ajukan melalui **[Form Lapor Salah Blokir](https://github.com/lonion-1/WhaleGuard/issues/new?template=lapor-spam.yml)** dengan memilih kategori **Salah Blokir (Allowlist)** agar nomor tersebut segera dihapus dari daftar blokir dan dilindungi permanen.

---

## 🔗 Aplikasi Pendamping & Ekosistem EazyWhale

* **Aplikasi Android (Mendukung Regex / URL Subscription):**
  * **[SpamBlocker](https://github.com/aj3423/SpamBlocker)** — Pemblokir panggilan & SMS *open-source* dengan otomatisasi pembaruan URL.
  * **[SpamBlocker Extended](https://f-droid.org/packages/spam.blocker.ext/)** — Varian *fork* di F-Droid dengan tambahan filter notifikasi aplikasi.
  * **[YourCall YourRule](https://play.google.com/store/apps/details?id=com.yourcall.yourrule)** — Pemblokir panggilan berbasis *subscribe* daftar Regex.
* **Aplikasi iOS (Mendukung Impor Daftar Nomor / CallKit):**
  * **[Call Ranger](https://apps.apple.com/app/call-ranger/id6743294898)** & **[WideProtect](https://apps.apple.com/us/app/wideprotect-spam-call-blocker/id1171024059)** — Pemblokir panggilan lokal untuk iPhone tanpa mengunggah data kontak.
* **Perlindungan Lapis Jaringan (DNS):**
  * **[WhaleList — EazyLife DNS Blocklists](https://github.com/lonion-1/WhaleList)** — Daftar blokir iklan, pelacak, *phishing*, dan domain judi online di tingkat DNS.

---

## 📄 Lisensi

* **Daftar Aturan (`rules/*.txt`):** Dilisensikan di bawah **[GNU GPL v3.0](LICENSE)**.
* **Skrip & Otomatisasi (`scripts/` & `.github/`):** Dilisensikan di bawah **[GNU AGPL v3.0](LICENSE)**.

---

<div align="center">
  <sub>🐾 Dirancang & diracik bersama oleh komunitas di seluruh dunia</sub><br>
  <sub>🔥 <b>SAYA AKAN LAWAN</b></sub>
</div>
<div align="right">
  <sub>love kiss… kiss… EazyWhale 🐳</sub><br>
  
</div>

# 🛡️ WhaleGuard — Benteng Privasi Telepon & SMS (SpamBlocker)

Kumpulan aturan **Regex** dan daftar blokir nomor spam khusus **Indonesia** yang dirancang untuk aplikasi pemblokir panggilan & SMS *open-source* **[SpamBlocker (Android)](https://github.com/aj3423/SpamBlocker)**.

* **100% Lokal & Privat (*On-Device*):** Tidak perlu mengunggah buku kontak atau riwayat panggilan ke server pihak ketiga seperti aplikasi *crowdsourced* pada umumnya.
* **Perlindungan OTP & Kurir Otomatis:** Setiap aturan diuji otomatis melalui simulator CI agar tidak pernah memblokir kode OTP bank, mutasi rekening, maupun notifikasi kurir paket resmi.

---

### 📦 Daftar Tautan Aturan (*Raw URLs*)

| Kategori | File | Aturan Aktif | Raw URL (Salin ke SpamBlocker) |
| :--- | :--- | :--- | :--- |
| **SMS Judi Online** | `rules/sms-judol-id.txt` | <!-- COUNT:rules/sms-judol-id.txt -->5<!-- /COUNT --> | `https://raw.githubusercontent.com/lonion-1/WhaleGuard/main/rules/sms-judol-id.txt` |
| **SMS Penipuan, Pinjol & `.apk`** | `rules/sms-scam-pinjol-id.txt` | <!-- COUNT:rules/sms-scam-pinjol-id.txt -->4<!-- /COUNT --> | `https://raw.githubusercontent.com/lonion-1/WhaleGuard/main/rules/sms-scam-pinjol-id.txt` |
| **Allowlist OTP & Kurir (Penting)** | `rules/sms-allowlist-otp.txt` | <!-- COUNT:rules/sms-allowlist-otp.txt -->3<!-- /COUNT --> | `https://raw.githubusercontent.com/lonion-1/WhaleGuard/main/rules/sms-allowlist-otp.txt` |
| **Nomor Spam & Penipu** | `rules/numbers-spam-id.txt` | <!-- COUNT:rules/numbers-spam-id.txt -->1<!-- /COUNT --> | `https://raw.githubusercontent.com/lonion-1/WhaleGuard/main/rules/numbers-spam-id.txt` |

---

### 📱 Cara Memasang di Aplikasi SpamBlocker
1. Unduh dan pasang aplikasi **SpamBlocker** melalui **[F-Droid](https://f-droid.org/packages/spam.blocker/)** atau halaman **[GitHub Releases](https://github.com/aj3423/SpamBlocker/releases)**.
2. Buka tab **Automations / Workflows** di dalam aplikasi SpamBlocker untuk menarik daftar secara berkala dari URL *Raw* di atas:
   * Gunakan tindakan **HTTP Request** menuju tautan *Raw* di atas $\rightarrow$ sambungkan ke **Regex Parse** (pisahkan per baris, abaikan baris berawalan `!`) $\rightarrow$ **Import to SMS/Number Rules**.
   * Pastikan aturan dari **`rules/sms-allowlist-otp.txt`** diimpor sebagai **Allow (Whitelist)** agar kode OTP selalu lolos.
3. Aktifkan opsi **Repeated Call** (misal: izinkan jika nomor yang sama menelepon 2x dalam 5 menit) agar panggilan darurat atau kurir paket tetap dapat terhubung.

---

### 🚨 Dapat SMS Judol Baru atau Nomor Penipu yang Lolos?
Laporkan langsung melalui **[Form Lapor Nomor Spam & SMS](https://github.com/lonion-1/WhaleGuard/issues/new?template=lapor-spam.yml)**—bot akan otomatis memeriksa apakah pola tersebut sudah tertangkap oleh filter saat ini.

---

<div align="center">
  <sub>🐾 Dirancang & diracik bersama oleh komunitas di seluruh dunia</sub><br>
  <sub>🔥 <b>SAYA AKAN LAWAN</b></sub>
</div>
<div align="right">
  <sub>love kiss… kiss… EazyWhale 🐳</sub><br>
</div>

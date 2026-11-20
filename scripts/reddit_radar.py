# Copyright (c) 2026 <EazyWhale>
# Licensed under the MIT License.

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

QUERIES = [
    "subreddit:indonesia (penipu OR scam OR pinjol OR judol)",
    "subreddit:indotech (penipu OR scam OR spam)",
]

RE_PHONE = re.compile(r"(?:\+?62|0)8[1-9][0-9\-\s]{6,13}[0-9]")
STATE_FILE = Path(".github/radar_seen.json")


def fetch_reddit(query: str) -> list[dict]:
    encoded = urllib.parse.quote(query)
    url = f"https://www.reddit.com/search.json?q={encoded}&sort=new&t=week&limit=25"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "WhaleGuard-IntelRadar/1.0 (by EazyWhale)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8", errors="ignore"))
            return [child["data"] for child in data.get("data", {}).get("children", [])]
    except Exception as e:
        print(f"Gagal menarik Reddit ({query}): {e}")
        return []


def main():
    seen_ids = set()
    if STATE_FILE.exists():
        try:
            seen_ids = set(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except Exception:
            seen_ids = set()

    temuan = []
    for q in QUERIES:
        for post in fetch_reddit(q):
            pid = post.get("id")
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)

            title = post.get("title", "")
            selftext = post.get("selftext", "")
            gabungan = f"{title}\n{selftext}"

            nomor_ditemukan = sorted({
                re.sub(r"[\s\-]", "", m.group(0))
                for m in RE_PHONE.finditer(gabungan)
            })

            # Hanya laporkan jika postingan mencantumkan nomor telepon
            if nomor_ditemukan:
                temuan.append({
                    "id": pid,
                    "title": title,
                    "url": f"https://www.reddit.com{post.get('permalink', '')}",
                    "numbers": nomor_ditemukan,
                    "snippet": selftext[:350].replace("\n", " ").strip(),
                })

    # Simpan riwayat ID postingan agar tidak dilaporkan berulang kali (maksimal 500 terakhir)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(sorted(seen_ids)[-500:], indent=2) + "\n", encoding="utf-8")

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if not temuan:
        print("Radar Reddit: Belum ada laporan nomor penipu baru minggu ini.")
        if gh_out:
            with open(gh_out, "a", encoding="utf-8") as f:
                f.write("has_findings=false\n")
        return

    lines = [
        "### 📡 Laporan Radar Intelijen Reddit (`WhaleGuard`)",
        "Bot menemukan postingan komunitas terbaru yang melaporkan dugaan penipuan beserta nomor telepon:",
        "",
    ]
    for item in temuan:
        nums_str = ", ".join(f"`{n}`" for n in item["numbers"])
        lines.append(f"#### 🔗 [{item['title']}]({item['url']})")
        lines.append(f"* **Nomor terdeteksi:** {nums_str}")
        if item["snippet"]:
            lines.append(f"* **Cuplikan cerita:** > {item['snippet']}...")
        lines.append("")

    lines.append("---")
    lines.append("*Catatan: Pastikan nomor di atas benar milik pelaku (bukan nomor korban/kurir yang bocor) sebelum memasukkannya ke `rules/numbers-spam-id.txt`.*")

    body_md = "\n".join(lines)
    print(body_md)

    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write("has_findings=true\n")
            f.write(f"issue_body<<EOF\n{body_md}\nEOF\n")


if __name__ == "__main__":
    main()
  

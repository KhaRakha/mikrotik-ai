# MikroTik AI Agent Automation

Sistem otomatisasi dan pemantauan jaringan **MikroTik RouterOS** berbasis **AI Agent (Hermes)** terintegrasi dengan **Telegram Bot**, dirancang khusus untuk administrator jaringan, teknisi, dan civitas akademika Pendidikan Teknik Informatika (PTI).

---

## 📌 Ringkasan Produk

Sistem ini memungkinkan administrator atau teknisi mengelola dan memonitor router MikroTik menggunakan **bahasa natural sehari-hari** melalui Telegram, tanpa perlu menghafal baris perintah (CLI) atau membuka Winbox secara manual.

```
USER (Telegram)
      │
      ▼ (Bahasa Natural)
TELEGRAM BOT
      │
      ▼
HERMES AI AGENT
  ├── Understanding (Memahami maksud)
  ├── Planning (Menentukan langkah pemeriksaan)
  ├── Tool Selection (Memilih fungsi MikroTik)
  └── Analysis (Menganalisis hasil diagnosa)
      │
      ▼
TOOL LAYER (Security & Confirmation)
      │
      ▼ (REST API / RouterOS API / SSH / Mock)
MIKROTIK ROUTEROS
```

### ✨ Prinsip Utama
* **Tidak Ada Hardcoded Command**: Bot tidak menggunakan pemetaan kaku seperti `if text == "/cekcpu"`. AI Agent menentukan sendiri langkah pemeriksaan berdasarkan konteks permasalahan.
* **Troubleshooting Multi-Langkah**: Pertanyaan seperti *"Kenapa internet kantor terasa lambat?"* secara otomatis dipecah menjadi:
  1. Pemeriksaan beban CPU dan RAM router
  2. Pemeriksaan link status dan traffic bandwidth interface WAN
  3. Pengujian konektivitas & packet loss (ping)
  4. Sintesis data untuk menyimpulkan akar penyebab masalah (*bottleneck*, saturasi bandwidth, atau gangguan ISP).
* **Two-Phase Confirmation Engine**: Operasi read-only berjalan otomatis, sedangkan operasi yang mengubah konfigurasi router (tambah user hotspot, hapus user, ubah interface) **wajib melalui konfirmasi** dengan tombol `[ ✅ YA ]` dan `[ ❌ BATAL ]`.
* **Dangerous Operation Protection**: Perintah destruktif seperti reset konfigurasi, factory reset, atau reboot ditolak secara tegas dengan peringatan risiko keamanan.
* **Auto Start & Always Running**: Dapat berjalan otomatis di latar belakang saat komputer menyala tanpa perlu membuka terminal atau VS Code.

---

## 📂 Struktur Proyek

```
mikrotik-ai/
├── PRD.md                       # Product Requirements Document
├── README.md                    # Dokumentasi lengkap proyek
├── requirements.txt             # Dependensi Python
├── .env.example                 # Template variabel lingkungan
├── .env                         # Konfigurasi lokal (Token bot, Whitelist, API Keys)
├── config/
│   ├── config.yaml              # Konfigurasi sistem (LLM, Security, Audit)
│   ├── devices.yaml             # Inventaris multi-perangkat (Kantor Utama, Cabang, Lab, Demo)
│   └── settings.py              # Loader konfigurasi terpadu
├── core/
│   ├── agent.py                 # Otak Hermes AI Agent (Reasoning, Planning, Tool Execution)
│   ├── prompts.py               # Prompt sistem dan persona Network Engineer
│   ├── security.py              # Whitelist guard, Dangerous command filter, RBAC
│   ├── confirmation.py          # State store & token approval untuk write actions
│   ├── monitor.py               # Proactive background monitoring & automated alerting
│   └── audit.py                 # SQLite & JSONL audit trail logger
├── mikrotik/
│   ├── base.py                  # Antarmuka abstrak klien MikroTik
│   ├── rest_client.py           # Klien MikroTik RouterOS v7 REST API (HTTP/HTTPS)
│   ├── ros_api_client.py        # Klien MikroTik RouterOS binary API (port 8728 / 8729)
│   ├── ssh_client.py            # Klien MikroTik SSH CLI
│   ├── mock_client.py           # Klien simulasi offline untuk pengujian & demo
│   ├── manager.py               # Manajemen multi-perangkat & resolusi nama alias
│   ├── discovery.py             # Pemindai jaringan (subnet scanner) untuk deteksi router
│   └── tools.py                 # Tool Layer function catalog & OpenAPI schemas (Router + Server)
├── bot/
│   ├── telegram_bot.py          # Aplikasi bot Telegram utama
│   ├── handlers.py              # Command handlers (/start, /status, /devices, /role, /audit, /discover)
│   └── formatters.py            # Pemformat kartu status, tombol inline, dan tabel
├── service/
│   ├── run_bot.py               # Entry point eksekusi bot
│   ├── watchdog.py              # Supervisor auto-recovery (restart otomatis jika crash)
│   ├── run.bat                  # Script Windows satu-klik untuk menjalankan bot
│   ├── start_background.vbs     # Peluncur latar belakang tanpa jendela console
│   ├── install_windows_task.ps1 # Pemasang Windows Scheduled Task (Boot Auto-Start)
│   └── uninstall_windows_task.ps1 # Penghapus Scheduled Task
├── skills/
│   └── mikrotik-automation/     # Hermes Agent Native Skill
│       ├── SKILL.md             # Definisi skill untuk Hermes CLI
│       └── scripts/
│           └── mikrotik_cli.py  # Utilitas baris perintah untuk tool execution
└── tests/
    ├── test_mikrotik_client.py  # Unit test operasi klien & simulasi
    ├── test_security.py         # Unit test keamanan, RBAC, dan filter perintah berbahaya
    ├── test_confirmation.py     # Unit test sistem konfirmasi
    ├── test_agent_tools.py      # Integrasi test skenario PRD (1, 2, 3) & hak akses Viewer
    ├── test_proactive_monitor.py # Unit test background proactive alerting (Down, Recovery, High CPU)
    ├── test_server_tools.py     # Unit test universal server & port tools
    └── test_audit_log.py        # Unit test pencatatan audit log
```

---

## ⚙️ Persiapan & Konfigurasi

### 1. Salin dan Sesuaikan `.env`
Salin template konfigurasi:
```powershell
Copy-Item .env.example .env
```
Isikan nilai pada file `.env`:
* `TELEGRAM_BOT_TOKEN`: Token bot dari [@BotFather](https://t.me/BotFather).
* `ALLOWED_TELEGRAM_IDS`: ID Telegram pengguna yang diizinkan (gunakan [@userinfobot](https://t.me/userinfobot) untuk melihat ID Anda).
* `GOOGLE_API_KEY`: API key Google Gemini (didapat di [Google AI Studio](https://aistudio.google.com/apikey)).
* `LLM_MODEL`: `gemini-3.6-flash` (atau model kompatibel lainnya).

*(Catatan: Jika Anda sudah menginstal Hermes Agent di komputer, sistem secara otomatis dapat membaca konfigurasi dari `~/.hermes/.env`).*

### 2. Mengaktifkan Layanan API pada Router MikroTik Fisik
Untuk router fisik (misal IP `10.20.33.240`), pastikan layanan API aktif melalui terminal Winbox:
```routeros
# Mengaktifkan REST API (RouterOS v7)
/ip service enable www-ssl
/ip service set www port=80 disabled=no

# ATAU mengaktifkan RouterOS API (port 8728)
/ip service enable api
```

### 3. Konfigurasi Inventaris Router (`config/devices.yaml`)
Daftarkan router jaringan Anda pada `config/devices.yaml`:
```yaml
devices:
  - id: "kantor_utama"
    name: "Kantor Utama"
    aliases: ["kantor utama", "router utama", "kantor"]
    host: "10.20.33.240"
    port: 80
    protocol: "rest"      # rest, api, ssh, atau mock
    username: "admin"
    password: ""
    is_default: true
    description: "Router MikroTik Utama Kantor PTI"

  - id: "simulasi_demo"
    name: "Simulasi Router"
    aliases: ["mock", "demo", "simulasi"]
    host: "127.0.0.1"
    port: 0
    protocol: "mock"
    is_default: false
    description: "Router Virtual untuk testing & demo offline"
```

---

## 🚀 Cara Menjalankan

### A. Menjalankan Langsung (Testing / Debugging)
Klik ganda file `service/run.bat` atau jalankan melalui PowerShell:
```powershell
.\service\run.bat
```

### B. Menjalankan di Latar Belakang (Silent Background Saat Ini)
Jalankan file VBS tanpa memunculkan jendela console hitam:
- Klik ganda `service/start_background.vbs`, ATAU
- Jalankan via terminal:
```powershell
wscript.exe .\service\start_background.vbs
```

### C. Menjalankan Otomatis Saat Windows Dinyalakan (Auto-Start)
Agar bot otomatis aktif setiap kali komputer/laptop menyala tanpa harus dijalankan manual:

#### Opsi 1: Klik Ganda (Paling Mudah, Tanpa Perlu Administrator)
1. Cukup klik ganda file [`service/pasang_autostart.bat`](file:///G:/My%20Drive/PENDIDIKAN%20TEKNIK%20INFORMATIKA/PTAKTIK%20INDUSTRI/mikrotik-ai/service/pasang_autostart.bat).
2. Bot akan otomatis terpasang di folder *Startup* Windows dan akan aktif di latar belakang setiap kali Windows menyala.
3. *Untuk mencopotnya kembali:* klik ganda file [`service/hapus_autostart.bat`](file:///G:/My%20Drive/PENDIDIKAN%20TEKNIK%20INFORMATIKA/PTAKTIK%20INDUSTRI/mikrotik-ai/service/hapus_autostart.bat).

#### Opsi 2: Windows Scheduled Task (Perlu Run as Administrator)
1. Buka PowerShell sebagai **Administrator**.
2. Jalankan:
```powershell
powershell -ExecutionPolicy Bypass -File .\service\install_windows_task.ps1
```
*Untuk menghapus task auto-start:*
```powershell
powershell -ExecutionPolicy Bypass -File .\service\uninstall_windows_task.ps1
```

### D. Cek Status & Mematikan Bot
Karena bot berjalan di latar belakang (tanpa jendela CMD), Anda dapat menggunakan utility berikut:
- **Cek apakah bot sedang jalan:** Klik ganda [`service/status_bot.bat`](file:///G:/My%20Drive/PENDIDIKAN%20TEKNIK%20INFORMATIKA/PTAKTIK%20INDUSTRI/mikrotik-ai/service/status_bot.bat)
- **Hentikan/matikan bot:** Klik ganda [`service/stop_bot.bat`](file:///G:/My%20Drive/PENDIDIKAN%20TEKNIK%20INFORMATIKA/PTAKTIK%20INDUSTRI/mikrotik-ai/service/stop_bot.bat)

---

## 💬 Panduan Interaksi Telegram

### Skenario 1 — Monitoring Kondisi Router
**User:**
> *"Coba cek kondisi MikroTik kantor utama."*

**Bot:**
```markdown
📡 MikroTik Kantor Utama

• Perangkat : RB750Gr3 (RouterOS 7.15.2)
• CPU Load  : 14%
• RAM Usage : 38.1% (Tersisa 158.4 MB)
• Uptime    : 12 hari, 8 jam, 44 menit
• WAN Link  : UP (ether1-WAN)
• Traffic   : Normal (Rx 3.42 Mbps / Tx 1.15 Mbps)

Kesimpulan:
🟢 Router dalam kondisi normal dan siap beroperasi.
```

---

### Skenario 2 — Troubleshooting Jaringan
**User:**
> *"Kenapa internet kantor terasa lambat?"*

**Bot:**
```markdown
🔎 Hasil Investigasi & Analisis Jaringan (Kantor Utama)

1. Kondisi Router:
   • CPU: 14% (Normal)
   • RAM: 38.1% (Stabil)
2. Interface WAN:
   • Status: UP
   • Traffic Rx: ~3.42 Mbps | Tx: ~1.15 Mbps (Tidak bottleneck)
3. Uji Konektivitas:
   • Ping ke 8.8.8.8: 14.5 ms (0% packet loss)

💡 Kesimpulan Diagnostik:
🟢 Router dan koneksi WAN ISP utama dalam kondisi sehat dan tidak ada bottleneck.
Kemungkinan kendala berada pada jaringan lokal (Wi-Fi access point atau batas queue/limit client tertentu).
```

---

### Skenario 3 — Konfigurasi & Sistem Konfirmasi
**User:**
> *"Buatkan user hotspot untuk tamu bernama Tamu123, aktif satu hari."*

**Bot:**
```markdown
⚠️ Konfirmasi Diperlukan

Target     : Kantor Utama
Aksi       : Create Hotspot User
Username   : Tamu123
Password   : passTamu123
Profil     : default
Masa Aktif : 1d

Lanjutkan pembuatan user?
[ ✅ YA (Setuju) ]    [ ❌ BATAL (Tolak) ]
```
*Jika pengguna menekan tombol `[ ✅ YA ]` atau membalas **"Ya"**:*
```markdown
✅ User hotspot 'Tamu123' berhasil dibuat dengan profil 'default' dan masa aktif '1d'.
Operasi selesai.
```

---

### Skenario 4 — Perlindungan Operasi Berbahaya
**User:**
> *"Reset MikroTik ke setelan pabrik."*

**Bot:**
```markdown
⚠️ OPERASI BERISIKO TINGGI DITOLAK

Operasi ini terdeteksi sebagai tindakan berbahaya (Reset / Reboot / Wipe):
• Kata kunci terdeteksi: 'reset'

Dampak risiko:
- Seluruh konfigurasi router dapat hilang
- Koneksi jaringan terputus total
- Akses manajemen router terisolasi

Operasi ini TIDAK TERSEDIA melalui AI Bot demi keamanan.
Silakan lakukan secara manual melalui Winbox atau konsol administrator fisik.
```

### Skenario 5 — Pengecekan Server & Layanan Port (Universal Monitoring)
**User:**
> *"Cek apakah port 80 pada server web 10.20.33.10 terbuka?"*

**Bot:**
```markdown
🖥️ Hasil Pengecekan Server / Service

• Target Host : 10.20.33.10
• Port        : 80
• Status      : 🟢 ONLINE / TERBUKA
• Latency     : 1.25 ms

Service pada server merespons dengan normal.
```

---

### Skenario 6 — Proactive Network Alerting (Notifikasi Otomatis Tanpa Ditanya)
Jika terjadi kendala koneksi atau utilisasi CPU router melonjak tinggi, bot secara proaktif mengirim peringatan langsung ke grup Telegram tim NOC / Administrator:
```markdown
🚨 PERINGATAN DINI JARINGAN (ROUTER DOWN)

Perangkat Kantor Utama (10.20.33.240) terdeteksi OFFLINE / Tidak Merespons!
• Protokol: API (Port 8728)
• Keterangan: Connection Refused / Timeout
• Waktu Terdeteksi: 2026-09-14 15:00:00

⚠️ Mohon segera periksa fisik perangkat atau jalur koneksi gateway.
```
Dan saat koneksi kembali:
```markdown
✅ JARINGAN PULIH (ROUTER RECOVERED)

Perangkat Kantor Utama (10.20.33.240) kini telah ONLINE KEMBALI!
• Latency: 4.5 ms
• Waktu Pemulihan: 2026-09-14 15:03:00

🟢 Layanan operasional jaringan telah normal kembali.
```

---

### Skenario 7 — Upgrade Firmware & RouterOS Langsung dari Telegram Bot
Administrator jaringan dapat memantau ketersediaan versi terbaru dan meng-upgrade sistem RouterOS maupun firmware bootloader (BIOS) RouterBOARD langsung melalui chat Telegram dengan perlindungan konfirmasi dua tahap dan pemantauan pemulihan otomatis:

1. **Pemeriksaan Firmware & Update:**
   - Command: `/firmware [nama_router] [channel]` atau `/check_update`
   - Bahasa Alami: *"Cek update firmware router"*, *"Apakah ada update RouterOS?"*, *"Status firmware"*, *"Cek frimware"*
   - Bot menyajikan perbandingan versi aktif vs rilis terbaru, channel (`stable`, `testing`, `long-term`), status bootloader hardware BIOS, dan tombol interaktif:
     - `[ 🚀 Upgrade RouterOS Sekarang ]` (jika paket baru tersedia)
     - `[ ⚡ Upgrade Bootloader Firmware ]` (jika firmware BIOS hardware baru tersedia)
     - `[ 🔄 Refresh / Cek Update ]`
     - `[ 🔁 Reboot Router ]`

2. **Eksekusi Upgrade Aman (Two-Phase Confirmation):**
   - Command: `/upgrade [nama_router] [channel] [force]` (contoh: `/upgrade Kantor_Utama stable`)
   - Bahasa Alami: *"Upgrade firmware router kantor utama"*, *"Perbarui firmware router"*
   - Bot memunculkan kartu peringatan keselamatan jaringan (router akan melakukan reboot otomatis dan offline selama 1-3 menit).
   - Administrator menyetujui melalui tombol `[ ✅ YA (Setuju) ]` atau ketik *"Ya"*. Router langsung mengunduh paket resmi dan melakukan flashing serta reboot secara aman.
   - Hak akses khusus Administrator: Pengguna dengan role Viewer dicegat dan ditolak secara otomatis demi keamanan jaringan.

3. **Reboot Router & Pembaruan Bootloader BIOS:**
   - Command: `/reboot [nama_router]` atau `/restart`
   - Setelah meng-upgrade bootloader BIOS RouterBOARD, bot secara otomatis menampilkan tombol `[ 🔄 Reboot Router Sekarang ]` agar firmware BIOS baru aktif.

4. **Pemantauan Otomatis Pasca-Upgrade (Proactive Recovery Watcher):**
   - Setelah perintah upgrade atau reboot dieksekusi, bot secara proaktif menjalankan *background watcher*.
   - Saat router selesai reboot dan kembali online, bot otomatis mengirimkan pesan pemberitahuan ke Telegram beserta durasi waktu offline dan status versi firmware terbarunya.

---

## 🛡️ Role-Based Access Control (RBAC)
Sistem membedakan izin pengguna secara hierarkis:
1. **Administrator (`ADMIN_TELEGRAM_IDS`)**: Memiliki akses penuh untuk monitoring, diagnosa, dan mengeksekusi konfirmasi perubahan konfigurasi (`WRITE`).
2. **Viewer / Operator (`VIEWER_TELEGRAM_IDS`)**: Hanya memiliki izin membaca status (*read-only*). Perubahan konfigurasi hotspot atau interface otomatis dicegat dan ditolak.
3. Pengguna dapat mengecek profil izinnya kapan saja melalui perintah:
   ```
   /role
   ```

---

## 🧪 Pengujian Otomatis (Unit & Integration Tests)

Seluruh komponen telah divalidasi dengan test suite unit dan integrasi:
```powershell
py -m pytest tests/ -v
```

Hasil pengujian mencakup **25 skenario verifikasi (100% PASSED)**:
* ✅ `test_scenario_1_monitoring` (Skenario 1 Monitoring)
* ✅ `test_scenario_2_troubleshooting` (Skenario 2 Troubleshooting Internet Lambat)
* ✅ `test_scenario_3_configuration_flow` (Skenario 3 Konfigurasi & Konfirmasi 2 Tahap)
* ✅ `test_viewer_write_restriction` (Pencegahan Operasi Write untuk Role Viewer)
* ✅ `test_dangerous_operation_rejection` (Penolakan Perintah Destruktif Reset/Reboot)
* ✅ `test_alert_on_device_down`, `test_recovery_alert_when_back_online`, `test_high_cpu_warning` (Proactive Monitor & Alerting Engine)
* ✅ `test_check_server_port_open`, `test_check_server_port_closed`, `test_ping_host` (Universal Server & Port Tools)
* ✅ `test_rbac_roles`, `test_classify_permission`, `test_dangerous_detection`, `test_redact_secrets`, `test_safe_queries` (RBAC & Keamanan)
* ✅ `test_connection`, `test_get_interfaces`, `test_get_resource`, `test_ping`, `test_hotspot_crud`, `test_interface_state` (Tool Layer)
* ✅ `test_cancel_confirmation`, `test_create_and_execute_confirmation` (Approval Token & Timeout)
* ✅ `test_log_and_retrieve` (Pencatatan Audit Trail SQLite & JSONL)

---

## 📜 Audit Trail & Logging

Setiap perintah yang masuk, aksi yang dijalankan, status konfirmasi, dan hasilnya dicatat secara otomatis ke dalam:
* **SQLite Database**: `data/audit.db` (tabel `audit_logs`)
* **JSON Lines**: `logs/audit.jsonl`

Administrator dapat melihat 8 aktivitas terakhir langsung dari Telegram dengan perintah:
```
/audit
```

---

## 🛠️ Integrasi Hermes Agent Native Skill

Skill ini juga telah didaftarkan langsung ke direktori native Hermes Agent di:
`C:\Users\LENOVO\AppData\Local\hermes\skills\mikrotik-automation\`

Sehingga jika Anda menggunakan CLI resmi Hermes Agent (`hermes`), AI Hermes langsung dapat memanggil skrip otomatisasi MikroTik secara otomatis.

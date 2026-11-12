PRD — AI Agent Telegram untuk Otomatisasi MikroTik

Nama Proyek: MikroTik AI Agent Automation
Platform: Telegram
AI Agent: Hermes Agent
Network Device: MikroTik RouterOS
Interface: Telegram Bot
Metode komunikasi MikroTik: RouterOS API / SSH / REST API
Target Pengguna: Admin jaringan, teknisi, dan mahasiswa PTI
Target Sistem: AI Agent yang fleksibel, otomatis, dan dapat berjalan sebagai background service

1. Ringkasan Produk

MikroTik AI Agent Automation adalah sistem yang mengintegrasikan Telegram Bot, Hermes AI Agent, dan MikroTik RouterOS.

Pengguna dapat memberikan instruksi kepada bot menggunakan bahasa natural, tanpa harus mengetahui command MikroTik.

Contoh:

"Coba cek kondisi MikroTik kantor utama."

"Kenapa internet kantor terasa lambat?"

"Tolong lihat apakah ada perangkat yang bermasalah."

"Cek user hotspot yang sedang aktif."

"Buatkan user hotspot untuk tamu bernama Tamu123, aktif satu hari."

Hermes akan memahami tujuan pengguna, menentukan langkah yang diperlukan, berkomunikasi dengan MikroTik, menganalisis hasil, kemudian memberikan jawaban melalui Telegram.

Sistem tidak boleh bergantung pada daftar command yang di-hardcode untuk setiap pertanyaan pengguna.

2. Permasalahan

Pengelolaan MikroTik secara manual memiliki beberapa kendala:

Pengguna harus memahami command RouterOS.
Monitoring harus dilakukan melalui Winbox/terminal.
Teknisi harus mengetahui konfigurasi setiap perangkat.
Pemeriksaan tertentu membutuhkan beberapa command sekaligus.
Tidak semua pengguna memahami konfigurasi jaringan.
Sistem bot konvensional biasanya hanya dapat menjalankan command yang sudah dibuatkan kodenya.

Contoh bot konvensional:

/cekcpu
/cekram
/cekinterface
/cekip
/cekhotspot

Model seperti ini kurang fleksibel karena setiap kemampuan baru membutuhkan perubahan kode.

3. Solusi

Membangun AI Agent menggunakan Hermes yang berfungsi sebagai operator jaringan berbasis AI.

Konsep:

USER
 │
 │ Bahasa Natural
 ▼
TELEGRAM BOT
 │
 ▼
HERMES AI AGENT
 │
 │ Memahami tujuan
 │ Menentukan langkah
 │ Memilih tool
 │ Menganalisis hasil
 ▼
MIKROTIK TOOL LAYER
 │
 ▼
MIKROTIK ROUTEROS

Dengan konsep ini, pengguna tidak perlu mengetahui command MikroTik.

4. Tujuan Produk

Sistem bertujuan untuk:

Mengontrol dan memonitor MikroTik melalui Telegram.
Menggunakan AI Agent untuk memahami bahasa natural.
Mengurangi kebutuhan pengguna untuk mengetahui command RouterOS.
Membuat sistem yang fleksibel terhadap berbagai jenis permintaan.
Memungkinkan AI melakukan beberapa langkah pemeriksaan secara otomatis.
Memungkinkan konfigurasi MikroTik melalui Telegram.
Memberikan konfirmasi sebelum perubahan konfigurasi.
Mencatat aktivitas pengguna.
Menjalankan bot secara otomatis tanpa menjalankan program secara manual.
Mendukung lebih dari satu MikroTik.
5. Prinsip Utama Sistem
5.1 Tidak Hardcode Per Pertanyaan

Sistem tidak boleh dibuat seperti:

Jika user berkata "cek CPU"
    jalankan fungsi cek CPU

Jika user berkata "cek RAM"
    jalankan fungsi cek RAM

Jika user berkata "cek interface"
    jalankan fungsi cek interface

Sebaliknya:

User
 ↓
Hermes memahami maksud
 ↓
Hermes menentukan informasi yang dibutuhkan
 ↓
Hermes memilih tool
 ↓
Tool berkomunikasi dengan MikroTik
 ↓
Hermes menganalisis hasil
6. Fleksibilitas AI

Sistem harus mampu menerima pertanyaan yang tidak ditentukan secara spesifik sebelumnya.

Contoh:

User

"Coba cari tahu kenapa koneksi internet kantor lambat."

Hermes dapat melakukan:

1. Cek resource router
2. Cek interface WAN
3. Cek traffic
4. Cek status interface
5. Cek route
6. Melakukan ping
7. Menganalisis hasil

Tidak perlu dibuat:

/cek_internet_lambat

secara khusus.

Contoh lain

User:

"Ada masalah nggak dengan router kantor utama?"

Hermes dapat melakukan pemeriksaan umum.

User:

"Coba lihat apa yang aneh dari traffic jaringan."

Hermes dapat mengambil data interface dan melakukan analisis.

User:

"Kenapa client saya tidak bisa akses internet?"

Hermes dapat menentukan pemeriksaan yang relevan berdasarkan informasi yang tersedia.

7. Scope Fitur
7.1 Telegram Interface

Telegram menjadi interface utama.

Bot harus dapat:

menerima pesan;
membalas pesan;
menerima bahasa natural;
mengirim status;
meminta konfirmasi;
mengirim hasil monitoring;
mengirim pesan error.
8. AI Agent Hermes

Hermes bertanggung jawab untuk:

Understanding

Memahami maksud pengguna.

Planning

Menentukan langkah yang diperlukan.

Tool Selection

Memilih tool MikroTik yang sesuai.

Execution

Menjalankan tool.

Analysis

Menganalisis hasil MikroTik.

Response

Memberikan hasil dalam bahasa manusia.

9. Tool Layer

Kode sistem menyediakan kemampuan dasar untuk berkomunikasi dengan MikroTik.

Contoh kemampuan:

connect_mikrotik
execute_routeros_operation
get_resource
get_interface
get_ip
get_route
get_firewall
get_dhcp
get_hotspot
ping
create_hotspot_user
update_configuration

Namun AI tidak harus memiliki command khusus untuk setiap kalimat pengguna.

Contoh:

"Cek apakah router sehat"

dapat menggunakan beberapa tool.

10. Monitoring Dinamis

Hermes harus mampu melakukan pemeriksaan sesuai kebutuhan.

Contoh permintaan:

"Cek kondisi router."

Hermes dapat menentukan:

/system/resource
/interface
/ip/address
/ip/route

Permintaan:

"Coba cek apakah ada masalah pada koneksi internet."

Hermes dapat melakukan beberapa pemeriksaan yang relevan.

Permintaan:

"Cek perangkat yang sedang menggunakan jaringan."

Hermes dapat mencari informasi DHCP/ARP/interface sesuai konteks.

11. MikroTik Device Management

Sistem mendukung beberapa perangkat.

Contoh:

MikroTik
├── Kantor Utama
├── Kantor Cabang
├── Lab
└── Server

User dapat mengatakan:

"Cek CPU kantor utama."

Hermes menentukan perangkat:

Kantor Utama
IP: 10.20.33.240

Kemudian melakukan pemeriksaan.

12. Device Discovery

Sistem dapat memiliki kemampuan mendeteksi perangkat MikroTik yang dapat dijangkau oleh server Hermes.

Konsep:

Hermes Server
     │
     ├── Scan/Discovery
     │
     ├── MikroTik A
     ├── MikroTik B
     └── MikroTik C

Namun perangkat yang belum terdaftar tidak boleh langsung dikonfigurasi.

Perangkat baru harus melalui proses:

Discovery
   ↓
Identifikasi
   ↓
Registrasi
   ↓
Validasi akses
   ↓
Siap digunakan
13. Monitoring yang Didukung

Pada tahap awal, sistem harus mampu mengambil informasi seperti:

System
CPU
Memory
Uptime
RouterOS version
Board
Architecture
Interface
Interface aktif
RX
TX
Link status
Traffic
Network
IP address
Route
ARP
DHCP
Hotspot
User
Active user
Profile
Firewall
Rules
Counter
Status
Log
System log
Warning
Error
Connectivity
Ping
TCP connection
Gateway connectivity
14. Konfigurasi MikroTik

AI juga dapat membantu konfigurasi.

Contoh:

"Buat user hotspot Tamu123 aktif selama satu hari."

Hermes:

Target:
Kantor Utama

Aksi:
Create Hotspot User

Username:
Tamu123

Masa aktif:
1 hari

Kemudian:

⚠️ Konfirmasi diperlukan.

Lanjutkan?

[ YA ] [ BATAL ]

Jika user memilih YA:

Executing...

Kemudian:

✅ User Tamu123 berhasil dibuat.
15. Confirmation System

Semua operasi yang mengubah konfigurasi harus melalui confirmation.

Read-only

Tidak perlu konfirmasi:

Cek CPU
Cek RAM
Cek traffic
Cek IP
Ping
Cek hotspot
Cek log
Configuration

Memerlukan konfirmasi:

Buat user
Hapus user
Ubah IP
Tambah firewall
Hapus firewall
Enable interface
Disable interface
16. Dangerous Operation Protection

Operasi berbahaya harus dibatasi.

Contoh:

Reset MikroTik
Factory reset
Hapus konfigurasi
Disable seluruh interface
Ubah konfigurasi management

Sistem tidak boleh menjalankannya hanya karena AI memahami perintah tersebut.

Contoh:

"Reset MikroTik."

Bot:

⚠️ OPERASI BERISIKO TINGGI

Reset dapat menyebabkan:
- konfigurasi hilang
- koneksi terputus
- akses router hilang

Operasi ini tidak tersedia melalui AI Bot.
Silakan lakukan secara manual melalui akses administrator.
17. Security
Telegram Whitelist

Hanya user yang diizinkan yang dapat menggunakan bot.

ALLOWED_TELEGRAM_IDS=123456789
Credential

Credential MikroTik tidak boleh dimasukkan ke prompt AI.

Credential disimpan pada configuration/environment yang aman.

Permission

AI harus memiliki batasan:

READ
WRITE
DANGEROUS

Contoh:

READ
  ↓
boleh otomatis

WRITE
  ↓
confirmation

DANGEROUS
  ↓
blocked / administrator only
18. Auto Start / Always Running

Ini merupakan requirement penting.

Bot harus dapat berjalan tanpa user menjalankan Hermes secara manual setiap kali komputer hidup.

Target:

Windows / Server menyala
        ↓
Hermes otomatis berjalan
        ↓
Telegram Gateway aktif
        ↓
AI Agent siap
        ↓
Bot ONLINE

Implementasi dapat menggunakan:

Windows Task Scheduler;
Windows Service;
atau mekanisme service/background process lain yang sesuai dengan deployment Hermes.

Target akhirnya:

User tidak perlu membuka VS Code atau PowerShell untuk menjalankan bot.

19. Auto Recovery

Jika Hermes mengalami crash:

Hermes berhenti
     ↓
Service mendeteksi
     ↓
Restart otomatis
     ↓
Bot kembali ONLINE

Jika koneksi MikroTik terputus:

MikroTik offline
     ↓
Bot memberikan status offline
     ↓
Tidak melakukan perubahan
     ↓
Saat koneksi kembali
     ↓
Bot dapat digunakan kembali
20. Error Handling

Jika MikroTik tidak dapat dijangkau:

❌ MikroTik tidak dapat dihubungi.

Target:
Kantor Utama

IP:
10.20.33.240

Status:
Connection Failed

Hermes juga harus dapat menjelaskan kemungkinan penyebab.

21. Logging

Semua aktivitas penting dicatat.

Contoh:

Timestamp:
2026-09-14 13:30

Telegram User:
123456789

Request:
"Cek kondisi router kantor utama"

Device:
Kantor Utama

Action:
MONITOR

Result:
SUCCESS

Untuk konfigurasi:

Action:
CREATE_HOTSPOT_USER

Confirmation:
YES

Result:
SUCCESS
22. Audit Trail

Administrator harus dapat mengetahui:

siapa yang menjalankan perintah;
kapan perintah dijalankan;
MikroTik mana yang digunakan;
tindakan apa yang dilakukan;
hasilnya;
apakah memerlukan konfirmasi.
23. Arsitektur Final
┌──────────────────────┐
│       USER           │
│      Telegram        │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│    TELEGRAM BOT      │
└──────────┬───────────┘
           │
           ▼
┌────────────────────────────┐
│       HERMES AI AGENT      │
│                            │
│ Understanding              │
│ Planning                   │
│ Tool Selection             │
│ Analysis                   │
└────────────┬───────────────┘
             │
             ▼
┌────────────────────────────┐
│       TOOL LAYER           │
│                            │
│ MikroTik Connection        │
│ RouterOS Operations        │
│ Security                   │
│ Confirmation               │
└────────────┬───────────────┘
             │
             ▼
┌────────────────────────────┐
│       MIKROTIK             │
│        RouterOS            │
└────────────────────────────┘
24. Contoh Alur Lengkap
Skenario 1 — Monitoring

User:

"Coba cek kondisi MikroTik kantor utama."

Hermes:

1. Identifikasi perangkat
2. Cek koneksi
3. Ambil resource
4. Ambil interface
5. Ambil network information
6. Analisis

Bot:

📡 MikroTik Kantor Utama

CPU       : 12%
Memory    : 38%
Uptime    : 12 hari
WAN       : UP
Traffic   : Normal

Kesimpulan:
🟢 Router dalam kondisi normal.
25. Skenario 2 — Troubleshooting

User:

"Internet kantor lambat, coba cari penyebabnya."

Hermes:

Planning:

→ Check router resource
→ Check WAN interface
→ Check traffic
→ Check gateway
→ Check connectivity
→ Analyze

Kemudian:

🔎 Hasil pemeriksaan

CPU router      : Normal
Memory          : Normal
WAN             : UP
Traffic         : Tinggi
Gateway         : Reachable
Internet ping   : Tinggi

Kesimpulan:
Kemungkinan bottleneck berada pada koneksi WAN karena
traffic sedang tinggi.

Tidak diperlukan command khusus:

/troubleshoot_internet
26. Skenario 3 — Konfigurasi

User:

"Buat user hotspot Tamu123 untuk tamu, aktif satu hari."

Hermes:

Memahami permintaan
       ↓
Identifikasi MikroTik
       ↓
Menyiapkan konfigurasi
       ↓
Meminta konfirmasi
       ↓
Execute
       ↓
Verifikasi
       ↓
Report

Bot:

⚠️ Konfirmasi

Username : Tamu123
Masa aktif : 1 hari

Lanjutkan?

User:

"Ya."

Bot:

⏳ Memproses...

✅ User berhasil dibuat.
27. Non-Functional Requirements
Reliability

Bot harus dapat berjalan dalam waktu lama tanpa perlu restart manual.

Security

Credential dan akses MikroTik harus dilindungi.

Flexibility

Sistem tidak boleh bergantung pada command yang di-hardcode untuk setiap kebutuhan.

Usability

Pengguna cukup menggunakan bahasa natural.

Maintainability

Penambahan kemampuan baru sebisa mungkin dilakukan melalui tool/permission layer tanpa mengubah seluruh sistem.

Performance

Respons monitoring sederhana harus dikembalikan dalam waktu yang wajar setelah koneksi tersedia.

28. MVP

Untuk versi pertama, fokus pada:

✅ Telegram
✅ Hermes
✅ Auto Start
✅ Telegram Whitelist
✅ Koneksi MikroTik
✅ Device Management
✅ Monitoring
✅ Ping
✅ AI Tool Calling
✅ Natural Language
✅ Confirmation
✅ Logging

Kemampuan konfigurasi awal:

✅ Create hotspot user
✅ Delete hotspot user
✅ Enable/disable interface

Operasi berbahaya:

❌ Factory reset
❌ Reset configuration
❌ Mass configuration
29. Target Akhir

Target proyek bukan sekadar:

"Bot Telegram yang bisa menjalankan command MikroTik."

Tetapi:

"AI Network Agent yang dapat menerima instruksi natural-language melalui Telegram, memahami tujuan pengguna, menentukan langkah pemeriksaan atau konfigurasi yang diperlukan, berinteraksi dengan MikroTik secara aman, menganalisis hasil, dan memberikan respons yang mudah dipahami tanpa mengharuskan setiap jenis permintaan dibuatkan kode secara manual."

Sehingga pola penggunaannya menjadi:

                     TELEGRAM
                         │
                         ▼
                 "Cek kenapa internet
                    kantor lambat"
                         │
                         ▼
                    HERMES AI
                         │
                ┌────────┴────────┐
                │                 │
             Planning          Analysis
                │                 │
                ▼                 │
           MikroTik Tools ────────┘
                │
                ▼
             MIKROTIK
                │
                ▼
          Hasil Pemeriksaan
                │
                ▼
             HERMES
                │
                ▼
             TELEGRAM

Intinya: code menjadi fondasi, bukan daftar semua hal yang bisa ditanyakan. Hermes menjadi pihak yang menentukan apa yang perlu dilakukan berdasarkan konteks permintaan user.
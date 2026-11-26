# Raspberry Pi 5 par AI Avatar Frame

Yeh project Windows laptop aur Raspberry Pi 5 (4 GB) dono par chalta hai — ek hi code, ek hi
`config/settings.toml`. Pi par apne aap halki settings lagti hain (`[pi.*]` sections), taaki board
zyada garam na ho aur load kam rahe.

## Hardware (zaroori)

| Cheez | Kyon |
|---|---|
| Raspberry Pi 5, 4 GB | Yahi target hai |
| **Official 27 W USB-C power supply** (5.1 V, 5 A) | Kam power wale charger se USB ports 600 mA tak seemit rehte hain aur board ruk sakta hai |
| **Active Cooler** (ya official case jisme fan hai) | Camera + browser lagataar chalte hain; bina cooling ke Pi garam hokar dheema ho jata hai |
| microSD 32 GB+ (A2) ya NVMe SSD | OS + models (~350 MB) + avatars |
| HDMI display + **micro-HDMI cable** | Pi 5 me micro-HDMI port hain |
| **USB microphone** (ya mic wala USB webcam) | Pi me mic nahi hota |
| **Speaker: HDMI display ke speaker ya USB speaker** | **Pi 5 me 3.5 mm headphone jack nahi hai** |
| Camera: USB webcam **ya** Raspberry Pi Camera Module 3 | Dono chalte hain (Camera Module `rpicam-vid` se padha jata hai) |
| Internet (Wi-Fi/LAN) | Gemini (sunna + sochna) aur Microsoft awaaz online hain |

## OS

**Raspberry Pi OS (64-bit) with desktop — Bookworm recommended.** Usme Python 3.11 hai (laptop wala
hi version), isliye sab kuch install hota hai, camera ke bhaav/ishaare (MediaPipe) bhi.
Naya **Trixie** bhi chalega: wahan Python 3.13 hai jiske liye MediaPipe nahi milta, isliye setup
script apne aap alag se Python 3.11 (uv se) laga deti hai.

## Setup (ek baar)

```bash
git clone <aapka-repo-url> ~/avatar-frame
cd ~/avatar-frame
bash scripts/pi/setup.sh
nano config/.env          # GEMINI_API_KEY=... (laptop wali key)
sudo reboot
```

Reboot ke baad frame apne aap full-screen khulta hai (Chromium kiosk). Script yeh sab karti hai:
system packages, Python 3.11 environment, models download (`backend/scripts/download_models.py`),
web page build, backend ko boot par chalana (systemd `avatar-frame`), aur desktop autostart.

## Avatars (`avtars/` folder)

Pi par nayi photo ka neural face banana bahut dheema (20–30 min) aur garam hai, isliye:

1. **Laptop par** photos `avtars/` me daalo aur chalao:
   ```
   backend\.venv\Scripts\python.exe backend\scripts\prepare_avatars.py
   ```
   Har nayi photo ~8 min leti hai. Bundles `avtars/prepared/<naam>/` me bante hain.
2. `avtars/` (prepared ke saath) git me commit karke push karo, Pi par `git pull`.
3. Pi par yeh avatars **turant** taiyaar milte hain; page khulte hi pichhla (ya pehla) avatar apne
   aap khulta hai, menu me thumbnails se badal sakte ho.

Pi par seedhe upload ki gayi nayi photo bhi chalti hai, bas halke (lightweight) animation se.

## Pi par kya alag hai (settings.toml `[pi.*]`)

| Setting | Laptop | Pi 5 |
|---|---|---|
| Camera image | 640×480 @15 | 480×360 @12 |
| Bhaav padhna | 2/sec | 1/sec |
| Neural face (nayi photo) | haan | nahi (avtars/ wale pehle se taiyaar) |
| Chehra draw | 60 fps | 30 fps |
| Offline Whisper | base | tiny (sirf jab internet na ho) |
| Offline models boot par load | haan | nahi (zaroorat par) |

## Rozana kaam

```bash
sudo systemctl status avatar-frame        # chal raha hai?
journalctl -u avatar-frame -f             # logs
sudo systemctl restart avatar-frame       # settings badalne ke baad
vcgencmd measure_temp                     # garmi (75 °C se neeche rakho)
bash scripts/pi/start.sh                  # service ke bina haath se chalana
bash scripts/pi/update.sh                 # laptop se push ki gayi nayi cheezein (avatars, code) lena
```

Sound na aaye: taskbar ke speaker icon se HDMI/USB output chuno. Mic na chale: USB mic lagao aur
page reload karo.

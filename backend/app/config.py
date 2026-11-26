from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "uploads"
AVATAR_DATA = ROOT / "avatar_data"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


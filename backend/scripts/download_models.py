"""Download the model files the avatar frame needs into .tools/models (Windows, Linux, Raspberry Pi).

    python backend/scripts/download_models.py            # everything for this device
    python backend/scripts/download_models.py --pi       # Raspberry Pi set (smaller Whisper)

Already present files are skipped. Only standard library + the backend venv are needed.
"""
import argparse
import platform
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / ".tools" / "models"
HF = "https://huggingface.co"
WHISPER_FILES = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]

COMMON = {
    # Face position for eye contact (OpenCV YuNet)
    "yunet/face_detection_yunet_2023mar.onnx":
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    # Face landmarks/expressions and hand gestures (MediaPipe), feelings, man/woman voice
    "vision/face_landmarker.task":
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task",
    "vision/gesture_recognizer.task":
        "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task",
    "vision/enet_b0_8_best_afew.onnx":
        "https://github.com/av-savchenko/face-emotion-recognition/raw/main/models/affectnet_emotions/onnx/enet_b0_8_best_afew.onnx",
    "vision/gender_googlenet.onnx":
        "https://github.com/onnx/models/raw/main/validated/vision/body_analysis/age_gender/models/gender_googlenet.onnx",
    # Offline Hindi voices (used when there is no internet)
    "piper/hi_IN-priyamvada-medium.onnx": f"{HF}/rhasspy/piper-voices/resolve/main/hi/hi_IN/priyamvada/medium/hi_IN-priyamvada-medium.onnx",
    "piper/hi_IN-priyamvada-medium.onnx.json": f"{HF}/rhasspy/piper-voices/resolve/main/hi/hi_IN/priyamvada/medium/hi_IN-priyamvada-medium.onnx.json",
    "piper/hi_IN-pratham-medium.onnx": f"{HF}/rhasspy/piper-voices/resolve/main/hi/hi_IN/pratham/medium/hi_IN-pratham-medium.onnx",
    "piper/hi_IN-pratham-medium.onnx.json": f"{HF}/rhasspy/piper-voices/resolve/main/hi/hi_IN/pratham/medium/hi_IN-pratham-medium.onnx.json",
}


def whisper(size):
    return {f"faster-whisper-{size}/{name}": f"{HF}/Systran/faster-whisper-{size}/resolve/main/{name}" for name in WHISPER_FILES}


def fetch(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = target.with_name(target.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "avatar-frame-setup"})
    with urllib.request.urlopen(request, timeout=60) as response, pending.open("wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while chunk := response.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r    {done * 100 // total:3d}%  {done / 1e6:6.1f} MB", end="", flush=True)
    print()
    pending.replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pi", action="store_true", help="Raspberry Pi set (Whisper tiny only)")
    args = parser.parse_args()
    on_pi = args.pi or (platform.machine() in ("aarch64", "arm64") and sys.platform.startswith("linux"))
    files = {**COMMON, **whisper("tiny"), **({} if on_pi else whisper("base"))}
    failed = []
    for relative, url in files.items():
        target = MODELS / relative
        if target.is_file() and target.stat().st_size > 0:
            print(f"  ok   {relative}")
            continue
        print(f"  get  {relative}")
        try:
            fetch(url, target)
        except Exception as error:  # keep going: most models are optional features
            print(f"  FAILED {relative}: {error}")
            failed.append(relative)
    print("Done." if not failed else f"Done, but {len(failed)} file(s) failed — run again to retry: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

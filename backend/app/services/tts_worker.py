"""One isolated Windows COM apartment per synthesis; no audio plays on the server."""
import sys


def main():
    import pyttsx3
    text = sys.stdin.buffer.read().decode("utf-8")
    errors = []
    engine = pyttsx3.init(driverName="sapi5")
    engine.connect("error", lambda name, exception: errors.append(exception))
    try:
        engine.setProperty("rate", int(sys.argv[2]) if len(sys.argv) > 2 else 175)
        engine.setProperty("volume", 1.0)
        engine.save_to_file(text, sys.argv[1])
        engine.runAndWait()
        if errors:
            raise RuntimeError("SAPI failed to synthesize speech") from errors[0]
    finally:
        engine.stop()


if __name__ == "__main__":
    main()

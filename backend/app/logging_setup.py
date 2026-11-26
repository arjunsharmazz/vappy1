"""One consistent log format for every module (vision, audio, brain, speech)."""
import logging


def setup_logging(level: str = "INFO"):
    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))
    if not any(getattr(h, "_living_frame", False) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s", "%H:%M:%S"))
        handler._living_frame = True
        root.addHandler(handler)
    # Every local HTTP call (llama.cpp, tests) would otherwise flood the log.
    logging.getLogger("httpx").setLevel(logging.WARNING)

from __future__ import annotations

import threading
import webbrowser

import uvicorn

from .config import load_config, validate_config


def main() -> None:
    cfg = load_config()
    errors = validate_config(cfg)
    if errors:
        print("Config errors:")
        for e in errors:
            print(f"  - {e}")
        print("Launching anyway — fix in the Configure modal.")

    threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{cfg.port}")).start()
    uvicorn.run("kollab.server:app", host="127.0.0.1", port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()

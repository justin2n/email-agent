"""
Entry point for hosting platforms.

Railpack (Railway's builder) looks for FastAPI, Flask or Django and, failing
that, runs `main.py` in the project root. This app is a stdlib http.server, so
none of its framework detectors fire - this file is the guaranteed launch path.

Locally you'd use `make app` or `python -m src.webapp`; this exists purely so a
build system with no start command configured still boots the right thing.
"""

from src.webapp import main

if __name__ == "__main__":
    raise SystemExit(main())

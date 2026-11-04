#!/usr/bin/env python3
"""Start the source-aware localization PoC.

Usage:
    python3 app.py               # http://127.0.0.1:8010/
    python3 app.py --open        # also open the browser
    python3 app.py --port 8080

No dependencies outside the Python standard library (Python 3.9+).
"""

from sourceaware.server import main

if __name__ == "__main__":
    raise SystemExit(main())

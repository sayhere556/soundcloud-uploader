"""Compatibility entry point. The standalone application now lives in sc.py."""
from sc import main

if __name__ == "__main__":
    raise SystemExit(main())

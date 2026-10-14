"""Entry point of `python -m simplicio_loop.review_gate`."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())

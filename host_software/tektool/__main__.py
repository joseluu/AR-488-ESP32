"""Entry point so `python -m host_software.tektool ...` works."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())

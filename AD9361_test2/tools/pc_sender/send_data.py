#!/usr/bin/env python3
import sys

from sender_core import parse_args, run_cli


if __name__ == "__main__":
    try:
        sys.exit(run_cli(parse_args()))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

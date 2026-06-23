#!/usr/bin/env python3
import sys

from receiver_core import parse_args, run_cli


if __name__ == "__main__":
    try:
        sys.exit(run_cli(parse_args()))
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

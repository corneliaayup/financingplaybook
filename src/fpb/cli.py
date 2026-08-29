from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from .config import load_config, validate_config
from .engine import score


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fpb")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("score")
    p.add_argument("--config", type=Path, default=Path("config"))
    p.add_argument("--record", type=Path, required=True)
    p.add_argument("--context", type=Path)
    args = ap.parse_args(argv)

    bundle = load_config(args.config)
    problems = validate_config(bundle)
    if problems:
        for x in problems:
            print(f"config: {x}", file=sys.stderr)
        return 3

    record = json.loads(args.record.read_text())
    context = json.loads(args.context.read_text()) if args.context else {}
    result = score(record, bundle, context)
    print(json.dumps(dataclasses.asdict(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

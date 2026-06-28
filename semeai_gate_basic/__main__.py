from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .gate import check_ai_answer


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SemeAI Gate Basic on one JSON request.")
    parser.add_argument("--input", "-i", help="Path to request JSON. Reads stdin if omitted.")
    parser.add_argument("--receipt-dir", help="Optional local receipt output directory.")
    args = parser.parse_args()

    if args.input:
        request = json.loads(Path(args.input).read_text(encoding="utf-8"))
    else:
        request = json.loads(sys.stdin.read())
    result = check_ai_answer(request, receipt_dir=args.receipt_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

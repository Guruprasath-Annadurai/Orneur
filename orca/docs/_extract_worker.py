"""Child process for ``orca.docs.safe_extract``: read ``<json header>\\n<file bytes>`` from stdin, write one JSON line to stdout. Never imported by the server."""
from __future__ import annotations

import json
import sys


def main() -> int:
    header = json.loads(sys.stdin.buffer.readline())
    data = sys.stdin.buffer.read()
    from orca.docs.extractor import extract

    try:
        text = extract(header["filename"], data)
        out = {"ok": True, "text": text}
    except ImportError as exc:
        out = {"ok": False, "kind": "unavailable", "message": str(exc)[:200]}
    except ValueError as exc:
        out = {"ok": False, "kind": "unsupported", "message": str(exc)[:200]}
    except MemoryError:
        out = {"ok": False, "kind": "resource", "message": "memory limit"}
    except Exception as exc:                                  # a malformed file: the parser's own message is not shown to users
        out = {"ok": False, "kind": "failed", "message": type(exc).__name__}
    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

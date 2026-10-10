#!/usr/bin/env bash
# Install the hashed RSE extra closure and audit that environment.
# A finding fails this script. There is no unconditional success override.
set -euo pipefail

cd "$(dirname "$0")/../.."

if command -v python >/dev/null 2>&1; then
  python -m pip install uv pip-audit
else
  python3 -m pip install uv pip-audit
fi
export PATH="${HOME}/.local/bin:${PATH}"

uv venv --clear --python 3.11 /tmp/rse-audit
uv pip install --python /tmp/rse-audit/bin/python --require-hashes -r requirements/rse.txt

site="$("/tmp/rse-audit/bin/python" -c "import site; print(site.getsitepackages()[0])")"
pip-audit --path "$site" --progress-spinner off

"/tmp/rse-audit/bin/python" -c "import pyhpke, cryptography, importlib.metadata as m; assert m.version('pyhpke') == '0.6.5'"

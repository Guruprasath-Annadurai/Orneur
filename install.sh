#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  ORNEUR — One-Line Installer
#
#  NOTE: this script installs the "orneur" PyPI package. As of the ORNEUR
#  corporate identity closure, that package has not yet been published --
#  see docs/orneur/brand/ORNEUR_PACKAGING_MIGRATION.md. Until it is, run
#  this from a cloned repository checkout instead of a hosted URL; there is
#  no verified ORNEUR download domain yet (the previous "orca.systems" URL
#  belonged to an unrelated third party, not this project -- see that same
#  doc for the evidence).
#  Usage (once published):  curl -fsSL <verified-orneur-domain>/install.sh | bash
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ORNEUR_VERSION="${ORNEUR_VERSION:-latest}"
VENV_DIR="${HOME}/.orca/venv"
BIN_DIR="${HOME}/.local/bin"
WRAPPER="${BIN_DIR}/orneur"

# ── Colors ──────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
    BOLD='\033[1m'; DIM='\033[2m'; CYAN='\033[36m'; GREEN='\033[32m'
    RED='\033[31m'; YELLOW='\033[33m'; RESET='\033[0m'
else
    BOLD=''; DIM=''; CYAN=''; GREEN=''; RED=''; YELLOW=''; RESET=''
fi

log()   { echo -e "${CYAN}[orneur]${RESET} $*"; }
ok()    { echo -e "${GREEN}[orneur]${RESET} $*"; }
warn()  { echo -e "${YELLOW}[orneur]${RESET} $*"; }
error() { echo -e "${RED}[orneur] ERROR:${RESET} $*" >&2; exit 1; }

# ── Banner ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}  ▓▓▓ ORNEUR — Intelligence, Without End.  ▓▓▓${RESET}"
echo -e "${DIM}  Your hardware. Your data. Your intelligence.${RESET}"
echo ""

# ── OS / arch check ─────────────────────────────────────────────────────────
OS="$(uname -s)"
ARCH="$(uname -m)"
log "Detected: ${OS} / ${ARCH}"

case "${OS}" in
    Linux|Darwin) ;;
    *) error "Unsupported OS: ${OS}. Install manually: pip install orneur" ;;
esac

# ── Python check ────────────────────────────────────────────────────────────
PYTHON=""
for py in python3.12 python3.11 python3 python; do
    if command -v "${py}" &>/dev/null; then
        ver="$("${py}" -c 'import sys; print(sys.version_info[:2])' 2>/dev/null)"
        if [[ "${ver}" == *"(3, 11)"* ]] || [[ "${ver}" == *"(3, 12)"* ]] || [[ "${ver}" == *"(3, 13)"* ]]; then
            PYTHON="${py}"
            break
        fi
    fi
done

if [ -z "${PYTHON}" ]; then
    error "Python 3.11+ is required.\n  Install from: https://python.org/downloads"
fi
log "Python: $(${PYTHON} --version)"

# ── Create venv ─────────────────────────────────────────────────────────────
log "Creating virtual environment at ${VENV_DIR}..."
mkdir -p "$(dirname "${VENV_DIR}")"
"${PYTHON}" -m venv "${VENV_DIR}"

PIP="${VENV_DIR}/bin/pip"
PYTHON_VENV="${VENV_DIR}/bin/python"

# ── Upgrade pip ─────────────────────────────────────────────────────────────
log "Upgrading pip..."
"${PYTHON_VENV}" -m pip install --upgrade pip --quiet

# ── Install orneur ──────────────────────────────────────────────────────────
if [ "${ORNEUR_VERSION}" = "latest" ]; then
    log "Installing orneur (latest)..."
    "${PIP}" install orneur --quiet
else
    log "Installing orneur==${ORNEUR_VERSION}..."
    "${PIP}" install "orneur==${ORNEUR_VERSION}" --quiet
fi
ok "orneur installed."

# ── Wrapper script ───────────────────────────────────────────────────────────
mkdir -p "${BIN_DIR}"
cat > "${WRAPPER}" << WRAPPER_EOF
#!/usr/bin/env bash
exec "${VENV_DIR}/bin/orneur" "\$@"
WRAPPER_EOF
chmod +x "${WRAPPER}"
ok "Wrapper created at ${WRAPPER}"

# ── PATH check ───────────────────────────────────────────────────────────────
if [[ ":${PATH}:" != *":${BIN_DIR}:"* ]]; then
    warn "${BIN_DIR} is not in your PATH."
    echo ""
    SHELL_RC=""
    case "${SHELL}" in
        */zsh)  SHELL_RC="${HOME}/.zshrc" ;;
        */bash) SHELL_RC="${HOME}/.bashrc" ;;
    esac
    if [ -n "${SHELL_RC}" ]; then
        echo -e "  Add to ${SHELL_RC}:"
        echo -e "  ${DIM}export PATH=\"\${HOME}/.local/bin:\${PATH}\"${RESET}"
        echo ""
        read -r -p "  Add it automatically? [Y/n] " ans
        ans="${ans:-Y}"
        if [[ "${ans}" =~ ^[Yy] ]]; then
            echo '' >> "${SHELL_RC}"
            echo 'export PATH="${HOME}/.local/bin:${PATH}"' >> "${SHELL_RC}"
            ok "Added to ${SHELL_RC}. Run: source ${SHELL_RC}"
        fi
    else
        echo -e "  Add ${BIN_DIR} to your PATH manually."
    fi
fi

# ── Ollama check ─────────────────────────────────────────────────────────────
echo ""
log "Checking Ollama..."
if command -v ollama &>/dev/null; then
    ok "Ollama found: $(ollama --version 2>/dev/null || echo 'installed')"
else
    warn "Ollama not found. Installing..."
    if [ "${OS}" = "Darwin" ]; then
        if command -v brew &>/dev/null; then
            brew install ollama --quiet && ok "Ollama installed via Homebrew."
        else
            warn "Homebrew not found. Download Ollama from: https://ollama.com/download"
        fi
    elif [ "${OS}" = "Linux" ]; then
        curl -fsSL https://ollama.com/install.sh | sh && ok "Ollama installed."
    fi
fi

# ── Final ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}  Installation complete!${RESET}"
echo ""
echo -e "  ${CYAN}orneur doctor --wizard${RESET}   ${DIM}— first-run setup${RESET}"
echo -e "  ${CYAN}orneur serve${RESET}             ${DIM}— launch the web UI${RESET}"
echo -e "  ${CYAN}orneur core chat${RESET}         ${DIM}— terminal chat${RESET}"
echo -e "  ${CYAN}orneur --help${RESET}            ${DIM}— all commands${RESET}"
echo ""
echo -e "  ${DIM}docs: https://github.com/Guruprasath-Annadurai/Orneur${RESET}"
echo ""

read -r -p "  Run first-time setup wizard now? [Y/n] " run_wizard
run_wizard="${run_wizard:-Y}"
if [[ "${run_wizard}" =~ ^[Yy] ]]; then
    "${WRAPPER}" doctor --wizard
fi

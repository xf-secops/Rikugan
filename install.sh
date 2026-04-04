#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# Rikugan — universal installer (Linux / macOS)
#
#   curl -fsSL https://raw.githubusercontent.com/buzzer-re/Rikugan/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/buzzer-re/Rikugan/main/install.sh | bash -s -- --ida
#   curl -fsSL https://raw.githubusercontent.com/buzzer-re/Rikugan/main/install.sh | bash -s -- --binja
#   curl -fsSL https://raw.githubusercontent.com/buzzer-re/Rikugan/main/install.sh | bash -s -- --both
#
# Environment variables:
#   RIKUGAN_DIR     — where to clone the repo   (default: ~/.rikugan)
#   RIKUGAN_BRANCH  — git branch to check out   (default: main)
#   IDADIR          — override IDA install dir  (forwarded to install_ida.sh)
#   IDA_PYTHON      — override Python for IDA    (forwarded to install_ida.sh)
#   BN_PYTHON       — override Python for BN     (forwarded to install_binaryninja.sh)
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_URL="https://github.com/buzzer-re/Rikugan.git"
INSTALL_DIR="${RIKUGAN_DIR:-$HOME/.rikugan}"
BRANCH="${RIKUGAN_BRANCH:-main}"

# ── Colors ───────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

info()   { printf "${CYAN}[*]${NC} %s\n" "$*"; }
ok()     { printf "${GREEN}[+]${NC} %s\n" "$*"; }
warn()   { printf "${YELLOW}[!]${NC} %s\n" "$*"; }
err()    { printf "${RED}[-]${NC} %s\n" "$*" >&2; }

banner() {
    printf "\n${BOLD}"
    cat << 'EOF'
    ╔══════════════════════════════════════════╗
    ║            六眼  Rikugan                 ║
    ║     Reverse Engineering AI Agent         ║
    ║        IDA Pro  ·  Binary Ninja          ║
    ╚══════════════════════════════════════════╝
EOF
    printf "${NC}\n"
}

# ── Parse arguments ──────────────────────────────────────────────────
TARGET=""
for arg in "$@"; do
    case "$arg" in
        --ida)       TARGET="ida"   ;;
        --binja|--bn) TARGET="binja" ;;
        --both)      TARGET="both"  ;;
        --help|-h)
            echo "Usage: curl -fsSL https://raw.githubusercontent.com/buzzer-re/Rikugan/main/install.sh | bash -s -- [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --ida       Install for IDA Pro only"
            echo "  --binja     Install for Binary Ninja only"
            echo "  --both      Install for both hosts"
            echo "  (no flag)   Auto-detect installed hosts"
            echo ""
            echo "Environment:"
            echo "  RIKUGAN_DIR=$INSTALL_DIR"
            echo "  RIKUGAN_BRANCH=$BRANCH"
            exit 0
            ;;
    esac
done

# ── Host detection ───────────────────────────────────────────────────
detect_ida() {
    if [[ "$(uname)" == "Darwin" ]]; then
        [[ -d "$HOME/.idapro" ]] && return 0
        [[ -d "$HOME/Library/Application Support/Hex-Rays/IDA Pro" ]] && return 0
        ls /Applications/IDA*.app &>/dev/null && return 0
        ls "$HOME/Applications/IDA"*.app &>/dev/null 2>&1 && return 0
    else
        [[ -d "$HOME/.idapro" ]] && return 0
        [[ -d "$HOME/.ida" ]] && return 0
        ls /opt/ida* &>/dev/null 2>&1 && return 0
    fi
    command -v ida64 &>/dev/null && return 0
    command -v idat64 &>/dev/null && return 0
    return 1
}

detect_binja() {
    if [[ "$(uname)" == "Darwin" ]]; then
        [[ -d "$HOME/Library/Application Support/Binary Ninja" ]] && return 0
        [[ -d "$HOME/.binaryninja" ]] && return 0
        [[ -d "/Applications/Binary Ninja.app" ]] && return 0
        [[ -d "$HOME/Applications/Binary Ninja.app" ]] && return 0
    else
        [[ -d "$HOME/.binaryninja" ]] && return 0
    fi
    return 1
}

# ── Prerequisites ────────────────────────────────────────────────────
check_prereqs() {
    if ! command -v git &>/dev/null; then
        err "git is required but not installed."
        if [[ "$(uname)" == "Darwin" ]]; then
            err "Install with: xcode-select --install"
        else
            err "Install with your package manager (apt install git / dnf install git)"
        fi
        exit 1
    fi

    if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
        warn "Python not found in PATH — the per-host installer will attempt to find the bundled Python."
    fi
}

# ── Clone or update ──────────────────────────────────────────────────
clone_or_update() {
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        info "Updating existing installation at $INSTALL_DIR..."
        git -C "$INSTALL_DIR" fetch origin "$BRANCH" --quiet
        git -C "$INSTALL_DIR" checkout "$BRANCH" --quiet 2>/dev/null || true
        git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH" --quiet
        ok "Updated to latest $BRANCH"
    else
        if [[ -d "$INSTALL_DIR" ]]; then
            warn "$INSTALL_DIR exists but is not a git repo — backing up"
            mv "$INSTALL_DIR" "${INSTALL_DIR}.bak.$(date +%s)"
        fi
        info "Cloning Rikugan into $INSTALL_DIR..."
        git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR" --quiet
        ok "Cloned successfully"
    fi
}

# ── Run installers ───────────────────────────────────────────────────
run_ida_installer() {
    local script="$INSTALL_DIR/install_ida.sh"
    if [[ ! -f "$script" ]]; then
        err "install_ida.sh not found in $INSTALL_DIR"
        return 1
    fi
    info "Running IDA Pro installer..."
    echo ""
    chmod +x "$script"
    bash "$script"
}

run_binja_installer() {
    local script="$INSTALL_DIR/install_binaryninja.sh"
    if [[ ! -f "$script" ]]; then
        err "install_binaryninja.sh not found in $INSTALL_DIR"
        return 1
    fi
    info "Running Binary Ninja installer..."
    echo ""
    chmod +x "$script"
    bash "$script"
}

# ── Main ─────────────────────────────────────────────────────────────
main() {
    banner
    check_prereqs

    # Auto-detect if no target specified
    if [[ -z "$TARGET" ]]; then
        local has_ida=false has_binja=false
        detect_ida   && has_ida=true
        detect_binja && has_binja=true

        if $has_ida && $has_binja; then
            TARGET="both"
            ok "Detected both IDA Pro and Binary Ninja"
        elif $has_ida; then
            TARGET="ida"
            ok "Detected IDA Pro"
        elif $has_binja; then
            TARGET="binja"
            ok "Detected Binary Ninja"
        else
            warn "No IDA Pro or Binary Ninja installation detected."
            warn "Installing anyway — use --ida or --binja to specify the target."
            warn "Defaulting to both."
            TARGET="both"
        fi
    fi

    info "Target: ${TARGET}"
    info "Install directory: ${INSTALL_DIR}"
    echo ""

    clone_or_update
    echo ""

    local failed=false

    case "$TARGET" in
        ida)
            run_ida_installer || failed=true
            ;;
        binja)
            run_binja_installer || failed=true
            ;;
        both)
            run_ida_installer || { warn "IDA installation failed"; failed=true; }
            echo ""
            run_binja_installer || { warn "Binary Ninja installation failed"; failed=true; }
            ;;
    esac

    echo ""
    if $failed; then
        warn "Installation completed with errors. Check the output above."
    else
        ok "Rikugan installation complete!"
    fi
    printf "${DIM}  Install location: ${INSTALL_DIR}${NC}\n"
    printf "${DIM}  To update later:  cd ${INSTALL_DIR} && git pull${NC}\n"
    echo ""
}

main

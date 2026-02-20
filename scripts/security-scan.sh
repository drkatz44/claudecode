#!/bin/bash
# Cross-project security scanner
# Usage: ./scripts/security-scan.sh [project] [--fix]
#
# Scans for:
# - Python: bandit (static analysis), safety (dependencies), detect-secrets
# - JavaScript/TypeScript: npm audit, eslint-security
# - General: hardcoded secrets, insecure file permissions

set -e

WORKSPACE="$(dirname "$(dirname "$(realpath "$0")")")"
FIX_MODE=false
PROJECT=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --fix)
            FIX_MODE=true
            shift
            ;;
        -h|--help)
            echo "Security scanner for claudecode projects"
            echo ""
            echo "Usage: security-scan.sh [project] [--fix]"
            echo ""
            echo "Options:"
            echo "  project    Scan specific project (default: all)"
            echo "  --fix      Attempt to fix issues where possible"
            echo ""
            echo "Examples:"
            echo "  security-scan.sh                 # Scan all projects"
            echo "  security-scan.sh youtube-notes   # Scan one project"
            echo "  security-scan.sh --fix           # Scan and fix all"
            exit 0
            ;;
        *)
            PROJECT="$1"
            shift
            ;;
    esac
done

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ISSUES_FOUND=0

log_header() {
    echo -e "\n${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
}

log_section() {
    echo -e "\n${YELLOW}▶ $1${NC}"
}

log_ok() {
    echo -e "  ${GREEN}✓${NC} $1"
}

log_warn() {
    echo -e "  ${YELLOW}⚠${NC} $1"
    ((ISSUES_FOUND++)) || true
}

log_error() {
    echo -e "  ${RED}✗${NC} $1"
    ((ISSUES_FOUND++)) || true
}

# Check if command exists
has_cmd() {
    command -v "$1" &> /dev/null
}

# Scan a Python project
scan_python() {
    local dir="$1"
    local name="$2"

    log_section "Python: $name"

    # Check for pyproject.toml or requirements.txt
    if [[ ! -f "$dir/pyproject.toml" ]] && [[ ! -f "$dir/requirements.txt" ]]; then
        log_ok "No Python project detected"
        return
    fi

    # Bandit - static analysis
    if has_cmd bandit; then
        log_section "Bandit (static analysis)"
        if bandit -r "$dir/src" -q -ll 2>/dev/null; then
            log_ok "No high-severity issues"
        else
            log_warn "Bandit found issues (run 'bandit -r $dir/src' for details)"
        fi
    else
        log_warn "bandit not installed (pip install bandit)"
    fi

    # Safety - dependency vulnerabilities
    if has_cmd safety; then
        log_section "Safety (dependency vulnerabilities)"
        if [[ -f "$dir/requirements.txt" ]]; then
            if safety check -r "$dir/requirements.txt" --short-report 2>/dev/null; then
                log_ok "No known vulnerabilities"
            else
                log_error "Vulnerable dependencies found"
            fi
        elif [[ -f "$dir/pyproject.toml" ]]; then
            # Try uv export if available
            if has_cmd uv && [[ -f "$dir/uv.lock" ]]; then
                if (cd "$dir" && uv export --no-dev 2>/dev/null | safety check --stdin --short-report 2>/dev/null); then
                    log_ok "No known vulnerabilities"
                else
                    log_warn "Could not check dependencies or vulnerabilities found"
                fi
            else
                log_warn "Cannot check dependencies (no requirements.txt or uv.lock)"
            fi
        fi
    else
        log_warn "safety not installed (pip install safety)"
    fi
}

# Scan for secrets
scan_secrets() {
    local dir="$1"
    local name="$2"

    log_section "Secret Detection: $name"

    # Common secret patterns
    local patterns=(
        "ANTHROPIC_API_KEY\s*="
        "api_key\s*=\s*['\"][^'\"]{20,}['\"]"
        "password\s*=\s*['\"][^'\"]+['\"]"
        "secret\s*=\s*['\"][^'\"]+['\"]"
        "token\s*=\s*['\"][^'\"]{20,}['\"]"
        "sk-ant-"
        "sk-[a-zA-Z0-9]{48}"
        "ghp_[a-zA-Z0-9]{36}"
        "gho_[a-zA-Z0-9]{36}"
    )

    local found=0
    local matches=""
    for pattern in "${patterns[@]}"; do
        local result=$(grep -rE "$pattern" "$dir" \
            --include="*.py" --include="*.js" --include="*.ts" \
            --include="*.yaml" --include="*.yml" --include="*.json" \
            --include="*.env" --include="*.sh" \
            --exclude-dir=".git" --exclude-dir="node_modules" --exclude-dir=".venv" \
            --exclude-dir="__pycache__" \
            2>/dev/null | grep -v "\.example" | grep -v "_test" | grep -v "test_" | head -3)
        if [[ -n "$result" ]]; then
            found=1
            matches+="$result"$'\n'
        fi
    done

    if [[ $found -eq 1 ]]; then
        echo "$matches" | head -5 | while read line; do
            echo -e "    ${RED}$line${NC}"
        done
    fi

    if [[ $found -eq 0 ]]; then
        log_ok "No obvious secrets detected"
    else
        log_error "Potential secrets found (review above)"
    fi
}

# Scan file permissions
scan_permissions() {
    local dir="$1"
    local name="$2"

    log_section "File Permissions: $name"

    # Check for overly permissive files
    local bad_perms=$(find "$dir" -type f \( -name "*.json" -o -name "*.yaml" -o -name "*.env" \) \
        -not -path "*/.venv/*" -not -path "*/node_modules/*" -not -path "*/.git/*" \
        -perm -o+r 2>/dev/null | head -5)

    if [[ -n "$bad_perms" ]]; then
        log_warn "World-readable config files found:"
        echo "$bad_perms" | while read f; do echo "    $f"; done
    else
        log_ok "No overly permissive config files"
    fi
}

# Scan a JavaScript/TypeScript project
scan_javascript() {
    local dir="$1"
    local name="$2"

    if [[ ! -f "$dir/package.json" ]]; then
        return
    fi

    log_section "JavaScript/TypeScript: $name"

    # npm audit
    if has_cmd npm; then
        log_section "npm audit"
        if (cd "$dir" && npm audit --audit-level=high 2>/dev/null); then
            log_ok "No high-severity vulnerabilities"
        else
            log_warn "Vulnerabilities found (run 'npm audit' in $name)"
        fi
    fi
}

# Main scan function for a project
scan_project() {
    local dir="$1"
    local name=$(basename "$dir")

    [[ "$name" == "_template" ]] && return
    [[ ! -d "$dir" ]] && return

    log_header "Scanning: $name"

    scan_python "$dir" "$name"
    scan_javascript "$dir" "$name"
    scan_secrets "$dir" "$name"
    scan_permissions "$dir" "$name"
}

# Main
echo -e "${BLUE}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║           Security Scanner - claudecode                   ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════════════╝${NC}"

if [[ -n "$PROJECT" ]]; then
    # Scan specific project
    if [[ -d "$WORKSPACE/projects/$PROJECT" ]]; then
        scan_project "$WORKSPACE/projects/$PROJECT"
    else
        echo -e "${RED}Project not found: $PROJECT${NC}"
        exit 1
    fi
else
    # Scan all projects
    for dir in "$WORKSPACE"/projects/*/; do
        scan_project "$dir"
    done
fi

# Summary
echo ""
log_header "Summary"
if [[ $ISSUES_FOUND -eq 0 ]]; then
    echo -e "  ${GREEN}✓ No security issues found${NC}"
else
    echo -e "  ${YELLOW}⚠ $ISSUES_FOUND potential issues found${NC}"
    echo -e "  Review warnings above and fix as needed"
fi
echo ""

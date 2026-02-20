#!/bin/bash
# Generate project status dashboard from CLAUDE.md files
# Usage: ./scripts/project-status.sh [--markdown]

WORKSPACE="$(dirname "$(dirname "$(realpath "$0")")")"
MARKDOWN=false

if [ "$1" = "--markdown" ] || [ "$1" = "-m" ]; then
    MARKDOWN=true
fi

# Colors (disabled for markdown output)
if [ "$MARKDOWN" = false ]; then
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    RED='\033[0;31m'
    DIM='\033[0;90m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    GREEN=''
    YELLOW=''
    RED=''
    DIM=''
    BOLD=''
    NC=''
fi

# Status emoji/indicator
status_indicator() {
    case "$1" in
        active)     echo -e "${GREEN}active${NC}" ;;
        paused)     echo -e "${YELLOW}paused${NC}" ;;
        planning)   echo -e "${DIM}planning${NC}" ;;
        complete)   echo -e "${GREEN}complete${NC}" ;;
        optimization) echo -e "${YELLOW}optimization${NC}" ;;
        *)          echo -e "${DIM}$1${NC}" ;;
    esac
}

if [ "$MARKDOWN" = true ]; then
    echo "# Project Status Dashboard"
    echo ""
    echo "Generated: $(date '+%Y-%m-%d %H:%M')"
    echo ""
    echo "| Project | Status | Purpose |"
    echo "|---------|--------|---------|"
fi

# Process each project
for dir in "$WORKSPACE"/projects/*/; do
    [ -d "$dir" ] || continue

    project=$(basename "$dir")
    [ "$project" = "_template" ] && continue

    claude_md="$dir/CLAUDE.md"

    if [ -f "$claude_md" ]; then
        # Extract status
        status=$(grep -m1 "^## Status" -A1 "$claude_md" | tail -1 | sed 's/^[[:space:]]*//' | tr -d '\r')
        [ -z "$status" ] && status="unknown"

        # Extract purpose (first line after ## Purpose)
        purpose=$(grep -m1 "^## Purpose" -A1 "$claude_md" | tail -1 | sed 's/^[[:space:]]*//' | tr -d '\r')
        [ -z "$purpose" ] && purpose="-"

        # Truncate purpose for display
        if [ ${#purpose} -gt 60 ]; then
            purpose="${purpose:0:57}..."
        fi

        if [ "$MARKDOWN" = true ]; then
            echo "| $project | $status | $purpose |"
        else
            printf "${BOLD}%-20s${NC} $(status_indicator "$status")\n" "$project"
            printf "  ${DIM}%s${NC}\n" "$purpose"
        fi
    else
        if [ "$MARKDOWN" = true ]; then
            echo "| $project | - | No CLAUDE.md |"
        else
            printf "${BOLD}%-20s${NC} ${DIM}no CLAUDE.md${NC}\n" "$project"
        fi
    fi
done

if [ "$MARKDOWN" = false ]; then
    echo ""
    echo -e "${DIM}Run 'cc <project>' to start working on a project${NC}"
fi

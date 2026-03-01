#!/bin/bash
# Project status dashboard for claudecode workspace
# Usage: ./scripts/project-status.sh [--markdown]

WORKSPACE="$(dirname "$(dirname "$(realpath "$0")")")"
MARKDOWN=false

if [ "$1" = "--markdown" ] || [ "$1" = "-m" ]; then
    MARKDOWN=true
fi

if [ "$MARKDOWN" = true ]; then
    echo "# Project Status Dashboard"
    echo ""
    echo "Generated: $(date '+%Y-%m-%d %H:%M')"
    echo ""
    echo "| Project | Status | Purpose |"
    echo "|---------|--------|---------|"
    for dir in "$WORKSPACE"/projects/*/; do
        [ -d "$dir" ] || continue
        project=$(basename "$dir")
        [ "$project" = "_template" ] && continue
        claude_md="$dir/CLAUDE.md"
        if [ -f "$claude_md" ]; then
            raw_status=$(grep -m1 "^## Status" -A1 "$claude_md" | tail -1 | tr -d '\r')
            pstatus=$(echo "$raw_status" | sed 's/\*\*//g' | awk '{print $1}' | tr '[:upper:]' '[:lower:]')
            purpose=$(grep -m1 "^## Purpose" -A1 "$claude_md" | tail -1 | sed 's/^[[:space:]]*//' | sed 's/\*\*//g' | tr -d '\r')
            [ ${#purpose} -gt 60 ] && purpose="${purpose:0:57}..."
            echo "| $project | $pstatus | $purpose |"
        else
            echo "| $project | - | No CLAUDE.md |"
        fi
    done
    exit 0
fi

# ── Terminal colors ──────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
DIM='\033[0;90m'
BOLD='\033[1m'
RESET='\033[0m'

# ── Box drawing ──────────────────────────────────────────────────────────────
TL='╭'; TR='╮'; BL='╰'; BR='╯'
H='─'; V='│'
ML='├'; MR='┤'

BOX_WIDTH=64

border_top()    { printf "${DIM}${TL}"; printf "${H}%.0s" $(seq 1 $((BOX_WIDTH-2))); printf "${TR}${RESET}\n"; }
border_bottom() { printf "${DIM}${BL}"; printf "${H}%.0s" $(seq 1 $((BOX_WIDTH-2))); printf "${BR}${RESET}\n"; }
border_mid()    { printf "${DIM}${ML}"; printf "${H}%.0s" $(seq 1 $((BOX_WIDTH-2))); printf "${MR}${RESET}\n"; }
border_row()    { # args: content (pre-colored), visible_len
    # layout: │(1) space(1) content(vis_len) pad space(1) │(1) = BOX_WIDTH
    content="$1"; vis_len="$2"
    pad=$((BOX_WIDTH - 4 - vis_len))
    [ $pad -lt 0 ] && pad=0
    printf "${DIM}${V}${RESET} %b%${pad}s ${DIM}${V}${RESET}\n" "$content" ""
}
border_blank()  { printf "${DIM}${V}${RESET}%$((BOX_WIDTH-2))s${DIM}${V}${RESET}\n" ""; }

# ── Parse projects ───────────────────────────────────────────────────────────
declare -a active_projects paused_projects planning_projects other_projects

for dir in "$WORKSPACE"/projects/*/; do
    [ -d "$dir" ] || continue
    project=$(basename "$dir")
    [ "$project" = "_template" ] && continue

    claude_md="$dir/CLAUDE.md"
    if [ -f "$claude_md" ]; then
        raw_status=$(grep -m1 "^## Status" -A1 "$claude_md" | tail -1 | tr -d '\r')
        pstatus=$(echo "$raw_status" | sed 's/\*\*//g' | awk '{print $1}' | tr '[:upper:]' '[:lower:]')
        purpose=$(grep -m1 "^## Purpose" -A1 "$claude_md" | tail -1 | sed 's/^[[:space:]]*//' | sed 's/\*\*//g' | tr -d '\r')
    else
        pstatus="unknown"
        purpose="No CLAUDE.md"
    fi

    # Check for uncommitted changes in this project's directory
    dirty=""
    if git -C "$WORKSPACE" status --short "projects/$project" 2>/dev/null | grep -q .; then
        dirty=" *"
    fi

    # Bucket by status
    entry="${project}|${pstatus}|${purpose}|${dirty}"
    case "$pstatus" in
        active)     active_projects+=("$entry") ;;
        paused)     paused_projects+=("$entry") ;;
        optimization|optimizing) paused_projects+=("$entry") ;;
        planning)   planning_projects+=("$entry") ;;
        *)          other_projects+=("$entry") ;;
    esac
done

# ── Render a group of projects ───────────────────────────────────────────────
render_project() {
    local icon="$1" icon_color="$2" project="$3" pstatus="$4" purpose="$5" dirty="$6"

    # Truncate purpose to fit: total visible = BOX_WIDTH-4; minus icon(2) name(name_col) space(1) dirty(2)
    local name_col=16
    local avail=$((BOX_WIDTH - 4 - 2 - name_col - 1 - 2))
    if [ ${#purpose} -gt $avail ]; then
        purpose="${purpose:0:$((avail-3))}..."
    fi

    # Dirty indicator
    local dirty_colored=""
    local dirty_len=0
    if [ -n "$dirty" ]; then
        dirty_colored="${YELLOW}${dirty}${RESET}"
        dirty_len=${#dirty}
    fi

    # Build colored line: icon name purpose dirty
    local colored_line="${icon_color}${icon}${RESET} ${BOLD}$(printf "%-${name_col}s" "$project")${RESET} ${DIM}${purpose}${RESET}${dirty_colored}"
    local vis_len=$((2 + name_col + 1 + ${#purpose} + dirty_len))

    border_row "$colored_line" "$vis_len"
}

render_group() {
    local header="$1"; shift
    local entries=("$@")
    [ ${#entries[@]} -eq 0 ] && return

    local header_colored="${BOLD}${header}${RESET}"
    border_row "$header_colored" "${#header}"
    for entry in "${entries[@]}"; do
        IFS='|' read -r project pstatus purpose dirty <<< "$entry"
        case "$pstatus" in
            active)             render_project "●" "$GREEN" "$project" "$pstatus" "$purpose" "$dirty" ;;
            paused)             render_project "◐" "$YELLOW" "$project" "$pstatus" "$purpose" "$dirty" ;;
            optimization*)      render_project "◑" "$YELLOW" "$project" "$pstatus" "$purpose" "$dirty" ;;
            planning)           render_project "○" "$DIM" "$project" "$pstatus" "$purpose" "$dirty" ;;
            *)                  render_project "·" "$DIM" "$project" "$pstatus" "$purpose" "$dirty" ;;
        esac
    done
}

# ── Header ───────────────────────────────────────────────────────────────────
datetime=$(date '+%a %b %-d · %I:%M %p')
title="CLAUDECODE WORKSPACE"
header_content="${BOLD}${CYAN}${title}${RESET}"
right="${DIM}${datetime}${RESET}"
# visible chars: title + spaces + datetime
title_len=${#title}
right_len=${#datetime}
pad=$((BOX_WIDTH - 4 - title_len - right_len))
[ $pad -lt 1 ] && pad=1
header_vis=$((title_len + pad + right_len))
header_colored="${BOLD}${CYAN}${title}${RESET}$(printf "%${pad}s")${DIM}${datetime}${RESET}"

echo ""
border_top
border_row "$header_colored" "$header_vis"
border_mid

# ── Project groups ───────────────────────────────────────────────────────────
if [ ${#active_projects[@]} -gt 0 ]; then
    border_blank
    render_group "ACTIVE" "${active_projects[@]}"
fi

if [ ${#paused_projects[@]} -gt 0 ]; then
    border_blank
    render_group "PAUSED" "${paused_projects[@]}"
fi

if [ ${#planning_projects[@]} -gt 0 ]; then
    border_blank
    render_group "PLANNING" "${planning_projects[@]}"
fi

if [ ${#other_projects[@]} -gt 0 ]; then
    border_blank
    render_group "OTHER" "${other_projects[@]}"
fi

# ── Usage stats ──────────────────────────────────────────────────────────────
STATS_SCRIPT="$(dirname "$(realpath "$0")")/usage-stats.py"
if [ -f "$STATS_SCRIPT" ]; then
    eval "$(python3 "$STATS_SCRIPT" 2>/dev/null)"
    if [ -n "$all_msgs" ]; then
        border_blank
        border_mid

        # Header row: label col + 3 value columns
        # Layout: 2sp label(14) | today(9) | week(9) | alltime(12) = 46 vis
        stat_hdr="$(printf "  %-14s%9s%9s%12s" "USAGE" "Today" "Week" "All-time")"
        stat_hdr_colored="${BOLD}$(printf "  %-14s" "USAGE")${RESET}${DIM}$(printf "%9s%9s%12s" "Today" "Week" "All-time")${RESET}"
        border_row "$stat_hdr_colored" "${#stat_hdr}"

        # Data rows
        render_stat_row() {
            local label="$1" dval="$2" wval="$3" aval="$4"
            local row="$(printf "  %-14s%9s%9s%12s" "$label" "$dval" "$wval" "$aval")"
            local row_colored="${DIM}$(printf "  %-14s" "$label")${RESET}$(printf "%9s%9s%12s" "$dval" "$wval" "$aval")"
            border_row "$row_colored" "${#row}"
        }

        render_stat_row "Messages"   "$day_msgs"   "$week_msgs"   "$all_msgs"
        render_stat_row "Tool calls" "$day_tools"  "$week_tools"  "$all_tools"
        render_stat_row "Sessions"   "$day_sessions" "$week_sessions" "$all_sessions"
    fi
fi

# ── Footer ───────────────────────────────────────────────────────────────────
border_blank
border_mid
footer="cc <project>  cc -c  cc -d  cc --security  cc -h"
footer_colored="${DIM}${footer}${RESET}"
border_row "$footer_colored" "${#footer}"
border_bottom
echo ""

#!/bin/bash
# Search across all project CLAUDE.md files and memory
# Usage: ./scripts/project-search.sh <query> [options]
#
# Options:
#   -a, --all      Search all files, not just CLAUDE.md
#   -c, --context  Show more context around matches

WORKSPACE="$(dirname "$(dirname "$(realpath "$0")")")"
MEMORY_DIR="$HOME/.claude/projects/-Users-drk-Code-claudecode/memory"

SEARCH_ALL=false
CONTEXT=2

while [[ $# -gt 0 ]]; do
    case "$1" in
        -a|--all)
            SEARCH_ALL=true
            shift
            ;;
        -c|--context)
            CONTEXT=5
            shift
            ;;
        -h|--help)
            echo "Search across project documentation"
            echo ""
            echo "Usage: project-search.sh <query> [options]"
            echo ""
            echo "Options:"
            echo "  -a, --all      Search all files, not just CLAUDE.md"
            echo "  -c, --context  Show more context around matches"
            echo ""
            echo "Examples:"
            echo "  project-search.sh 'browser automation'"
            echo "  project-search.sh 'pytest' --all"
            exit 0
            ;;
        *)
            QUERY="$1"
            shift
            ;;
    esac
done

if [ -z "$QUERY" ]; then
    echo "Usage: project-search.sh <query> [options]"
    exit 1
fi

echo "Searching for: $QUERY"
echo "─────────────────────────────────────────"

if [ "$SEARCH_ALL" = true ]; then
    # Search all project files
    grep -rn --color=always -C "$CONTEXT" "$QUERY" \
        "$WORKSPACE/projects" \
        "$WORKSPACE/CLAUDE.md" \
        "$MEMORY_DIR" \
        --include="*.md" \
        --include="*.py" \
        --include="*.yaml" \
        --include="*.json" \
        2>/dev/null | sed "s|$WORKSPACE/||g" | sed "s|$HOME/|~/|g"
else
    # Search only CLAUDE.md files and memory
    grep -n --color=always -C "$CONTEXT" "$QUERY" \
        "$WORKSPACE"/projects/*/CLAUDE.md \
        "$WORKSPACE/CLAUDE.md" \
        "$MEMORY_DIR"/*.md \
        2>/dev/null | sed "s|$WORKSPACE/||g" | sed "s|$HOME/|~/|g"
fi

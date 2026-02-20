# Workspace: claudecode

## Overview
Multi-project workspace for collaborative development with Claude Code.

## Project Status

| Project | Status | Description |
|---------|--------|-------------|
| **market-agent** | 🟢 active | Market analysis, screening, backtesting → feeds tastytrade |
| **tastytrade** | 🟢 active | Options strategy construction via tasty-agent MCP |
| **home-assistant** | 🟡 paused | Grocery/meal automation; store browser integrations pending login |
| **youtube-notes** | 🟢 active | YouTube transcription + Claude summarization |
| **pfas-analysis** | 🟡 optimization | LC-MS method adaptation (Waters→Shimadzu 8060) |
| **4711** | 🔴 sensitive | Private legal/workplace matter - see project CLAUDE.md |
| **EPA QA** | 🟢 active | EPA bureaucracy navigation, QAPPs, SOPs |
| **chatgpt-import** | ⚪ planning | Import/search ChatGPT exports |

## Structure
```
projects/           # All projects
  <name>/           # Each has own CLAUDE.md
  _template/        # Copy for new projects
docs/
  decisions.md      # Architectural decision log
```

## Quick Reference

### Common Commands
```bash
# Enter any project
cd projects/<name> && uv sync

# Run tests (Python projects)
uv run pytest

# Market analysis
cd projects/market-agent && uv run python scripts/pipeline.py

# YouTube notes
cd projects/youtube-notes && uv run youtube-notes summarize VIDEO_ID
```

### MCP Servers Available
- **polygon-io** - Market data, news, fundamentals
- **tasty-agent** - Broker connectivity, options, greeks

## Conventions
- Each project has CLAUDE.md with context, key files, current state
- Conventional commits: `feat|fix|docs|refactor|test: description`
- Python: uv, pytest, ruff
- TypeScript: pnpm, tsx, vitest

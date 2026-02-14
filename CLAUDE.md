# Workspace: claudecode

## Overview
Multi-project workspace for collaborative development with Claude Code.

## Structure
```
projects/       # All projects live here
  _template/    # Copy this to start new projects
  <name>/       # Individual projects
docs/           # Cross-project documentation
  decisions.md  # Architectural decision log
```

## Active Projects
- **chatgpt-import** - Import/index ChatGPT exports for search and Claude context
- **youtube-notes** - Transcribe YouTube videos and generate meeting note summaries
- **market-agent** - Financial markets analysis, screening, and trading signal generation
- **tastytrade** - Options trading strategy and analysis platform via tasty-agent MCP
- **pfas-analysis** - PFAS LC-MS/MS method adaptation (Waters→Shimadzu 8060) and data processing

## Conventions
- Each project has its own CLAUDE.md with project-specific context
- Use conventional commits: feat|fix|docs|refactor|test: description
- Update decisions.md for significant architectural choices

## Tech Stack Reference
- TypeScript: pnpm, tsx, vitest
- Python: uv, pytest, ruff
- Go: standard modules
- React: Next.js, Tailwind
- CI/CD: GitHub Actions

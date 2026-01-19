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
<!-- Update this list as projects are added -->
None yet.

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

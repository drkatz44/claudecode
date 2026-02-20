# Performance Optimization Analysis

Analyze the codebase for performance issues and optimization opportunities.

## Instructions

When this command is invoked, perform a comprehensive performance analysis of the current project or specified files. Focus on these key areas:

### 1. Database Query Issues
- **N+1 queries**: Loops that execute queries inside iterations
- **Missing indexes**: Queries filtering/sorting on non-indexed columns
- **Unbounded queries**: SELECT without LIMIT on large tables
- **Inefficient JOINs**: Cartesian products, missing WHERE clauses
- **Connection pooling**: Connection creation inside hot paths

### 2. Algorithm Efficiency
- **Time complexity**: O(n²) or worse in hot paths
- **Nested loops**: Triple-nested loops, repeated iterations
- **Redundant computation**: Same calculation repeated in loops
- **String concatenation**: Building strings in loops (use join/StringBuilder)
- **Sorting**: Unnecessary sorts, sorting already-sorted data

### 3. Memory Management
- **Memory leaks**: Unclosed resources, growing collections
- **Large object allocation**: Creating large objects in loops
- **Unnecessary copies**: Copying data when references suffice
- **Buffer sizing**: Undersized buffers causing reallocations
- **Lazy loading**: Loading entire datasets when pagination needed

### 4. Caching Opportunities
- **Repeated API calls**: Same external request made multiple times
- **Expensive computations**: Pure functions called with same inputs
- **Static data**: Loading config/reference data repeatedly
- **HTTP responses**: Responses that could be cached
- **Database results**: Queries that return same results frequently

## Output Format

Report findings in this format:

```
## Performance Analysis: [project/file]

### Critical Issues (fix immediately)
- **[Issue Type]** at `file:line`
  - Problem: [description]
  - Impact: [estimated impact]
  - Fix: [suggested solution]

### Warnings (should fix)
- **[Issue Type]** at `file:line`
  - Problem: [description]
  - Fix: [suggested solution]

### Optimization Opportunities
- **[Opportunity]** at `file:line`
  - Current: [what it does now]
  - Suggested: [optimization]
  - Benefit: [expected improvement]

### Summary
- Critical: N issues
- Warnings: N issues
- Opportunities: N identified
```

## Analysis Approach

1. First, identify the project type and key files:
   - Read CLAUDE.md for project context
   - Find entry points, hot paths, data access layers

2. For Python projects, focus on:
   - SQLAlchemy/Django ORM queries (check for N+1)
   - List comprehensions vs generators
   - `@lru_cache` opportunities
   - Async/await patterns

3. For JavaScript/TypeScript projects, focus on:
   - React re-renders, missing useMemo/useCallback
   - Promise.all for parallel operations
   - Bundle size, tree shaking opportunities

4. Use the Grep tool to find patterns:
   ```
   # N+1 pattern (query in loop)
   for.*:\n.*\.query\(

   # Unbounded queries
   SELECT.*FROM(?!.*LIMIT)

   # String concatenation in loop
   for.*:\n.*\+=.*str
   ```

5. Prioritize findings by:
   - Frequency (hot path vs cold path)
   - Data size (scales with N)
   - User impact (latency, memory)

## Arguments

- `$ARGUMENTS` - Optional: specific file or directory to analyze (defaults to current project)

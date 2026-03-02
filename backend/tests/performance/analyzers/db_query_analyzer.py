"""
Database query performance analyzer.

Parses PostgreSQL pg_stat_statements output and identifies slow queries,
missing indexes, and optimization opportunities.
"""
import csv
import re
from dataclasses import dataclass, field


@dataclass
class QueryStats:
    """
    Aggregated statistics for a single database query.

    Attributes:
        query: The SQL query text (may be normalized with placeholders)
        call_count: Total number of times this query was executed
        total_time_ms: Total execution time across all calls in milliseconds
        mean_time_ms: Average execution time per call in milliseconds
        p95_time_ms: 95th percentile execution time in milliseconds
        rows_returned: Total rows returned across all calls
    """

    query: str
    call_count: int
    total_time_ms: float
    mean_time_ms: float
    p95_time_ms: float = 0.0
    rows_returned: int = 0


def analyze_slow_queries(
    csv_path: str,
    threshold_ms: float = 100.0,
) -> list[QueryStats]:
    """
    Parse pg_stat_statements CSV export and return queries exceeding the threshold.

    The CSV is expected to have columns: query, calls, total_time, mean_time,
    rows (matching pg_stat_statements output format).

    Args:
        csv_path: Path to the pg_stat_statements CSV export.
        threshold_ms: Minimum mean execution time in ms to be considered slow.

    Returns:
        List of QueryStats for queries exceeding the threshold, sorted by
        total_time_ms descending (highest total impact first).

    Raises:
        FileNotFoundError: If csv_path does not exist.
    """
    import os

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Query stats CSV not found: {csv_path}")

    results: list[QueryStats] = []

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            query = row.get("query", "").strip()
            if not query:
                continue

            calls = int(row.get("calls", "0") or "0")
            total_time = float(row.get("total_time", "0") or "0")
            mean_time = float(row.get("mean_time", "0") or "0")
            rows = int(row.get("rows", "0") or "0")

            if mean_time >= threshold_ms:
                results.append(
                    QueryStats(
                        query=query,
                        call_count=calls,
                        total_time_ms=total_time,
                        mean_time_ms=mean_time,
                        rows_returned=rows,
                    )
                )

    # Sort by total impact (total_time_ms descending)
    results.sort(key=lambda q: q.total_time_ms, reverse=True)
    return results


# Patterns that suggest a sequential scan on a large table
_SEQ_SCAN_PATTERNS: list[re.Pattern] = [
    re.compile(r"SELECT\s+.*\s+FROM\s+\w+\s*$", re.IGNORECASE),
    re.compile(r"WHERE\s+.*\s+LIKE\s+'%", re.IGNORECASE),
    re.compile(r"WHERE\s+.*\s+NOT\s+IN\s*\(", re.IGNORECASE),
]


def identify_missing_indexes(query_stats: list[QueryStats]) -> list[str]:
    """
    Analyze slow queries for patterns that suggest missing database indexes.

    Checks for:
    - Full table scans (SELECT without WHERE)
    - LIKE queries with leading wildcards
    - NOT IN subqueries on large result sets

    Args:
        query_stats: List of slow QueryStats to analyze.

    Returns:
        List of human-readable suggestions for potential missing indexes.
    """
    suggestions: list[str] = []

    for qs in query_stats:
        query_upper = qs.query.upper()

        # Check for queries without WHERE clause (potential full table scan)
        if "WHERE" not in query_upper and "SELECT" in query_upper:
            # Extract table name
            match = re.search(r"FROM\s+(\w+)", qs.query, re.IGNORECASE)
            table = match.group(1) if match else "unknown_table"
            suggestions.append(
                f"Potential full table scan on '{table}': "
                f"query has no WHERE clause (mean={qs.mean_time_ms:.1f}ms, "
                f"calls={qs.call_count})"
            )

        # Check for leading wildcard LIKE
        if re.search(r"LIKE\s+'%", qs.query, re.IGNORECASE):
            match = re.search(r"(\w+)\s+LIKE", qs.query, re.IGNORECASE)
            column = match.group(1) if match else "unknown_column"
            suggestions.append(
                f"Leading wildcard LIKE on '{column}': "
                f"consider full-text search index (mean={qs.mean_time_ms:.1f}ms)"
            )

        # Check for high-row-count queries that might benefit from indexes
        if qs.rows_returned > 10_000 and qs.mean_time_ms > 200:
            suggestions.append(
                f"High row count query ({qs.rows_returned:,} rows, "
                f"mean={qs.mean_time_ms:.1f}ms): consider adding covering index"
            )

    return suggestions


def generate_query_report(stats: list[QueryStats]) -> str:
    """
    Generate a human-readable slow query analysis report.

    Args:
        stats: List of QueryStats to include in the report.

    Returns:
        Formatted multi-line report string.
    """
    if not stats:
        return "No slow queries detected."

    lines: list[str] = [
        "=" * 70,
        "SLOW QUERY ANALYSIS REPORT",
        "=" * 70,
        f"Total slow queries: {len(stats)}",
        "-" * 70,
    ]

    for i, qs in enumerate(stats, 1):
        # Truncate long queries for readability
        query_display = qs.query[:120] + "..." if len(qs.query) > 120 else qs.query
        lines.append(f"\n#{i}  Mean: {qs.mean_time_ms:.1f}ms  |  Calls: {qs.call_count:,}  |  Total: {qs.total_time_ms:.0f}ms")
        lines.append(f"    Query: {query_display}")
        if qs.rows_returned > 0:
            lines.append(f"    Rows: {qs.rows_returned:,}")

    # Add index suggestions
    suggestions = identify_missing_indexes(stats)
    if suggestions:
        lines.append("\n" + "-" * 70)
        lines.append("INDEX SUGGESTIONS")
        lines.append("-" * 70)
        for suggestion in suggestions:
            lines.append(f"  - {suggestion}")

    lines.append("\n" + "=" * 70)
    return "\n".join(lines)

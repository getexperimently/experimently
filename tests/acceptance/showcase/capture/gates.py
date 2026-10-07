"""The capture gates that judge recorded data: pure functions over numbers.

Each answers ``(ok, numbers, why)``; ``why`` is the refusal text when not ok.
They are unit tested on planted inputs (``backend/tests/unit/showcase``).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from showcase.capture import config, guard

Verdict = Tuple[bool, Dict[str, Any], str]


def frame_times(entries: Sequence[Mapping[str, Any]]) -> Verdict:
    """Frames exist and their times strictly increase from 0."""
    times = [int(e["t_ms"]) for e in entries]
    numbers = {"frames": len(times)}
    if not times:
        return False, numbers, "no frame was captured"
    if times[0] < 0 or any(b <= a for a, b in zip(times, times[1:])):
        return False, numbers, "frame times do not strictly increase"
    return True, numbers, ""


def freeze(
    entries: Sequence[Mapping[str, Any]],
    duration_ms: int,
    holds_ms: Sequence[int],
    still: Sequence[Tuple[int, int]],
    *,
    slack_ms: int = config.FREEZE_SLACK_MS,
) -> Verdict:
    """No stretch without a new frame longer than the longest hold plus slack.

    *still* lists spans where a still page is the point (a card scene), which
    are not counted.
    """
    longest_hold = max(holds_ms) if holds_ms else 0
    limit = longest_hold + slack_ms
    times = [int(e["t_ms"]) for e in entries] + [duration_ms]
    worst = (0, 0, 0)
    for a, b in zip(times, times[1:]):
        # The part of the gap outside every still span is what counts.
        covered = sum(max(0, min(b, e) - max(a, s)) for s, e in still)
        gap = (b - a) - covered
        if gap > worst[0]:
            worst = (gap, a, b)
    numbers = {"longest_gap_ms": worst[0], "limit_ms": limit}
    if worst[0] > limit:
        return (
            False,
            numbers,
            f"no new frame for {worst[0]} ms ({worst[1]}-{worst[2]} ms); the longest"
            f" hold is {longest_hold} ms",
        )
    return True, numbers, ""


def black(
    entries: Sequence[Mapping[str, Any]],
    lumas: Sequence[float],
    duration_ms: int,
    still: Sequence[Tuple[int, int]],
    *,
    threshold: float = config.BLACK_LUMA,
    limit_ms: int = config.BLACK_MS,
) -> Verdict:
    """No dark stretch longer than *limit_ms* outside *still* spans."""
    if len(lumas) != len(entries):
        return (
            False,
            {"frames": len(entries), "read": len(lumas)},
            "not every frame was read",
        )
    times = [int(e["t_ms"]) for e in entries] + [duration_ms]
    run_from: Optional[int] = None
    longest = 0
    for index, luma in enumerate(lumas):
        t = times[index]
        in_still = any(s <= t < e for s, e in still)
        if luma < threshold and not in_still:
            if run_from is None:
                run_from = t
            longest = max(longest, times[index + 1] - run_from)
        else:
            run_from = None
    numbers = {
        "longest_dark_ms": longest,
        "limit_ms": limit_ms,
        "darkest": round(min(lumas), 1) if lumas else None,
    }
    if longest > limit_ms:
        return False, numbers, f"the page is dark for {longest} ms"
    return True, numbers, ""


def payoff_still(
    entries: Sequence[Mapping[str, Any]], payoffs: Sequence[Mapping[str, Any]]
) -> Verdict:
    """U5: no new frame during a payoff hold (frames arrive only on change)."""
    worst = []
    for hold in payoffs:
        inside = [
            int(e["t_ms"])
            for e in entries
            if hold["from_ms"] + 100 < int(e["t_ms"]) < hold["to_ms"]
        ]
        worst.append(
            {
                "where": hold["where"],
                "ms": hold["to_ms"] - hold["from_ms"],
                "frames": len(inside),
            }
        )
    numbers = {"payoffs": worst}
    short = [w for w in worst if w["ms"] < config.PAYOFF_MS]
    moving = [w for w in worst if w["frames"]]
    if not payoffs:
        return False, numbers, "the storyboard has no payoff hold"
    if short:
        return False, numbers, f"{short[0]['where']}: payoff held {short[0]['ms']} ms"
    if moving:
        return (
            False,
            numbers,
            f"{moving[0]['where']}: the page changed during the payoff",
        )
    return True, numbers, ""


#: How far the computed zoom may be from ``config.ZOOM`` (CSS keeps 7 digits).
ZOOM_TOLERANCE = 1e-4


def zoom(measured: Mapping[str, Any]) -> Verdict:
    """C1: <body> has ``config.ZOOM`` as Chromium computed it, and <html> has none."""
    body, html = measured.get("body"), measured.get("html")
    numbers = {"body": body, "html": html, "wanted_body": round(config.ZOOM, 6)}
    if not all(isinstance(v, (int, float)) for v in (body, html)):
        return False, numbers, f"the page's zoom could not be read ({dict(measured)})"
    if abs(html - 1) > ZOOM_TOLERANCE:
        return False, numbers, f"<html> is zoomed {html:g}; the zoom belongs on <body>"
    if abs(body - config.ZOOM) > ZOOM_TOLERANCE:
        return (
            False,
            numbers,
            f"<body> is zoomed {body:g}, not {config.ZOOM:.6f}: the frames would not"
            " be the layout the storyboard was written for",
        )
    return True, numbers, ""


def needle_count(static: Sequence[str], kept: Iterable[str]) -> Verdict:
    """Gate 6's count: every static needle, plus each kept value, exactly."""
    static_set = set(static)
    kept_set = set(kept) - static_set
    total = len(static_set | kept_set)
    numbers = {"static": len(static_set), "kept": len(kept_set), "total": total}
    if total == 0:
        return False, numbers, "0 needles: refusing to scan"
    if len(static_set) != len(config.STATIC_NEEDLES) or not static_set <= set(
        config.STATIC_NEEDLES
    ):
        return False, numbers, "the static needles are not the four the tool carries"
    if total != len(static_set) + len(kept_set):
        return False, numbers, "needle count does not add up"
    return True, numbers, ""


def child_environments(
    started: Sequence[Mapping[str, Any]], allowed: Set[str]
) -> Verdict:
    """EM condition 10: every child's environment names only allow-listed keys."""
    extra: Dict[str, List[str]] = {}
    for child in started:
        unexpected = sorted(set(child["env_keys"]) - allowed)
        if unexpected:
            extra[str(child["name"])] = unexpected
    numbers = {"children": len(started), "unexpected": extra}
    if extra:
        name, keys = next(iter(extra.items()))
        return False, numbers, f"{name} was started with {', '.join(keys)}"
    return True, numbers, ""


def allowed_env_keys() -> Set[str]:
    """Every key a child may be given: the passed ones and the tool's settings."""
    keys = set(guard.PASSED) | set(guard.DOCKER_PASSED)
    keys |= set(
        guard.api_settings(
            api_port=1, dashboard_port=1, postgres_port=1, profile="core"
        )
    )
    keys |= set(guard.dashboard_settings(api_port=1, profile="core"))
    return keys

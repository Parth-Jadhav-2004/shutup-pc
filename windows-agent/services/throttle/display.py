from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

FIVE_HOUR_MINS = 300
WEEKLY_MINS = 10080
MONTHLY_MIN_MINS = 28 * 1440
MONTHLY_MINS = 30 * 1440
REQUEST_BUCKET_KEYS = ("gpt-4", "gpt-4o", "default")


def clamp_percent(value: Any, *, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return min(100.0, max(0.0, number))


def to_epoch_seconds(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, str) and "T" in value and not value.strip().isdigit():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return int(parsed.timestamp())
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return int(number / 1000) if number > 1e12 else int(number)


def percent_window(
    used_percent: Any,
    resets_at: Any = None,
    window_duration_mins: int | float | None = None,
    *,
    default_used: float | None = 0.0,
) -> dict | None:
    used = clamp_percent(used_percent, default=default_used)
    if used is None:
        return None
    window: dict[str, Any] = {
        "usedPercent": used,
        "remainingPercent": 100.0 - used,
        "resetsAt": to_epoch_seconds(resets_at),
    }
    if window_duration_mins is not None:
        try:
            window["windowDurationMins"] = int(window_duration_mins) or MONTHLY_MINS
        except (TypeError, ValueError):
            window["windowDurationMins"] = MONTHLY_MINS
    return window


def format_cents_left(cents: Any) -> str | None:
    try:
        number = float(cents)
    except (TypeError, ValueError):
        return None
    dollars = max(0.0, number) / 100.0
    if dollars >= 100:
        return f"${round(dollars)} left"
    if dollars >= 10:
        return f"${dollars:.0f} left"
    return f"${dollars:.2f} left"


def format_requests_left(remaining: Any) -> str | None:
    try:
        number = float(remaining)
    except (TypeError, ValueError):
        return None
    return f"{max(0, round(number))} left"


def is_cursor_free_plan(plan_type: str | None) -> bool:
    return str(plan_type or "").lower() in {"free", "hobby"}


def is_codex_free_plan(plan_type: str | None) -> bool:
    return str(plan_type or "").lower() == "free"


def format_reset_label(resets_at: Any, now_ms: float | None = None) -> str:
    if resets_at is None:
        return ""
    try:
        reset_ms = float(resets_at) * 1000.0
    except (TypeError, ValueError):
        return ""
    now = now_ms if now_ms is not None else datetime.now(timezone.utc).timestamp() * 1000.0
    diff_sec = max(0, int((reset_ms - now + 999) // 1000))
    if diff_sec == 0:
        return "Resets now"
    days = diff_sec // 86400
    hours = (diff_sec % 86400) // 3600
    minutes = (diff_sec % 3600) // 60
    if days >= 7:
        stamped = datetime.fromtimestamp(reset_ms / 1000.0).strftime("%a, %b %d")
        return f"Resets {stamped}"
    if days:
        return f"Resets in {days}d {hours}h"
    if hours:
        return f"Resets in {hours}h {minutes}m"
    return f"Resets in {minutes} min"


_GEMINI_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?")
_GEMINI_TIER_RANK = (
    ("ultra", 50),
    ("pro", 40),
    ("thinking", 30),
    ("flash-lite", 15),
    ("flash lite", 15),
    ("flash", 20),
    ("lite", 10),
)


def antigravity_model_score(window: dict | None) -> tuple[int, int, int, int]:
    if not isinstance(window, dict):
        return (0, 0, 0, 0)
    text = f"{window.get('label') or ''} {window.get('modelId') or window.get('model_id') or ''}".lower()
    gemini = 1 if "gemini" in text else 0
    major = minor = 0
    match = _GEMINI_VERSION_RE.search(text)
    if match:
        major = int(match.group(1))
        minor = int(match.group(2) or 0)
    tier = 0
    for name, rank in _GEMINI_TIER_RANK:
        if name in text:
            tier = rank
            break
    return (major, minor, tier, gemini)


def pick_latest_antigravity_window(windows: Any) -> dict | None:
    candidates = [window for window in (windows or []) if isinstance(window, dict)]
    if not candidates:
        return None
    named = [window for window in candidates if antigravity_model_score(window) > (0, 0, 0, 0)]
    pool = named or candidates
    return max(pool, key=antigravity_model_score)


def used_percent_for_provider(provider: str, data: dict | None) -> float | None:
    if not data:
        return None
    if provider == "antigravity":
        latest = pick_latest_antigravity_window(data.get("windows"))
        if latest:
            return clamp_percent(latest.get("usedPercent"))
        return clamp_percent(data.get("usedPercent"))
    if provider == "cursor":
        included = data.get("included") or {}
        return clamp_percent(included.get("usedPercent"))
    if provider == "claude":
        return _max_used(data.get("fiveHour"), data.get("weekly"))
    if data.get("isFree"):
        return clamp_percent((data.get("monthly") or {}).get("usedPercent"))
    return _max_used(data.get("fiveHour"), data.get("weekly"), data.get("monthly"))


def _max_used(*windows: Any) -> float | None:
    values = [clamp_percent((window or {}).get("usedPercent") if isinstance(window, dict) else None) for window in windows]
    numbers = [value for value in values if value is not None]
    return max(numbers) if numbers else None


def _limit_row(label: str, window: dict | None, primary: bool = False) -> dict | None:
    if not isinstance(window, dict):
        return None
    used = clamp_percent(window.get("usedPercent"))
    if used is None:
        return None
    remaining = clamp_percent(window.get("remainingPercent"))
    if remaining is None:
        remaining = 100.0 - used
    resets_at = window.get("resetsAt")
    return {
        "label": label,
        "used_percent": used,
        "remaining_percent": remaining,
        "resets_at": resets_at,
        "reset_label": format_reset_label(resets_at),
        "primary": primary,
    }


def limits_for_provider(provider: str, data: dict | None) -> list[dict]:
    if not data:
        return []
    if provider == "claude":
        return [
            row
            for row in (
                _limit_row("Current session", data.get("fiveHour"), True),
                _limit_row("All models", data.get("weekly"), False),
            )
            if row
        ]
    if provider == "cursor":
        included_label = "Fast requests" if data.get("layout") == "requests" else "Cursor Models"
        return [
            row
            for row in (
                _limit_row(included_label, data.get("included"), True),
                _limit_row("Other Models", data.get("api"), False),
            )
            if row
        ]
    if provider == "codex":
        if data.get("isFree"):
            return [row for row in (_limit_row("Monthly limit", data.get("monthly"), True),) if row]
        return [
            row
            for row in (
                _limit_row("5-hour limit", data.get("fiveHour"), True),
                _limit_row("Weekly limit", data.get("weekly"), False),
            )
            if row
        ]
    if provider == "antigravity":
        latest = pick_latest_antigravity_window(data.get("windows"))
        if not latest:
            return []
        row = _limit_row(latest.get("label") or latest.get("group") or "Gemini", latest, True)
        return [row] if row else []
    return []


def cycle_window_mins(start: int | None, end: int | None) -> int:
    if start is None or end is None or end <= start:
        return MONTHLY_MINS
    return max(1, round((end - start) / 60))


def month_after(epoch_seconds: int | None) -> int | None:
    if epoch_seconds is None:
        return None
    dt = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
    month = dt.month + 1
    year = dt.year + (1 if month > 12 else 0)
    month = 1 if month > 12 else month
    try:
        next_dt = dt.replace(year=year, month=month)
    except ValueError:
        next_dt = dt.replace(year=year, month=month, day=28)
    return int(next_dt.timestamp())


def pick_request_bucket(usage: Any) -> dict | None:
    if not isinstance(usage, dict):
        return None
    for key in REQUEST_BUCKET_KEYS:
        bucket = usage.get(key)
        if isinstance(bucket, dict) and float(bucket.get("maxRequestUsage") or 0) > 0:
            return bucket
    best = None
    best_max = 0.0
    for key, bucket in usage.items():
        if key == "startOfMonth" or not isinstance(bucket, dict):
            continue
        try:
            maximum = float(bucket.get("maxRequestUsage") or 0)
        except (TypeError, ValueError):
            continue
        if maximum <= 0:
            continue
        if best is None or maximum > best_max:
            best = bucket
            best_max = maximum
    return best


def plan_name_from(plan_info: Any, membership_type: Any) -> str | None:
    block = plan_info.get("planInfo") if isinstance(plan_info, dict) else None
    name = None
    if isinstance(block, dict):
        name = block.get("planName")
    if not name and isinstance(plan_info, dict):
        name = plan_info.get("planName")
    name = name or membership_type
    return str(name) if name else None


def normalize_cursor_usage(
    usage: Any = None,
    plan_info: Any = None,
    membership_type: Any = None,
    request_usage: Any = None,
) -> dict:
    plan_type = plan_name_from(plan_info, membership_type)
    is_free = is_cursor_free_plan(plan_type)
    plan_usage = usage.get("planUsage") if isinstance(usage, dict) else None

    if isinstance(plan_usage, dict):
        start = to_epoch_seconds(usage.get("billingCycleStart") if isinstance(usage, dict) else None)
        billing_end = usage.get("billingCycleEnd") if isinstance(usage, dict) else None
        if billing_end is None and isinstance(plan_info, dict):
            nested = plan_info.get("planInfo")
            if isinstance(nested, dict):
                billing_end = nested.get("billingCycleEnd")
            else:
                billing_end = plan_info.get("billingCycleEnd")
        end = to_epoch_seconds(billing_end)
        mins = cycle_window_mins(start, end)
        limit_cents = float(plan_usage.get("limit") or 0) or float(
            ((plan_info or {}).get("planInfo") or {}).get("includedAmountCents") or 0
            if isinstance(plan_info, dict)
            else 0
        )
        included_spend = plan_usage.get("includedSpend")
        remaining_raw = plan_usage.get("remaining")
        try:
            remaining_cents = float(remaining_raw)
            remaining_ok = True
        except (TypeError, ValueError):
            remaining_cents = None
            remaining_ok = False
        if not remaining_ok and limit_cents > 0:
            try:
                remaining_cents = max(0.0, limit_cents - float(included_spend))
            except (TypeError, ValueError):
                remaining_cents = None
        total_percent = plan_usage.get("totalPercentUsed")
        try:
            total_percent_n = float(total_percent)
            total_ok = True
        except (TypeError, ValueError):
            total_ok = False
            total_percent_n = 0.0
        if not total_ok and limit_cents > 0:
            try:
                total_percent_n = (float(included_spend) / limit_cents) * 100.0
            except (TypeError, ValueError):
                total_percent_n = 0.0
        auto_percent = plan_usage.get("autoPercentUsed")
        try:
            cursor_models_percent = float(auto_percent)
        except (TypeError, ValueError):
            cursor_models_percent = total_percent_n
        api = None
        api_percent = plan_usage.get("apiPercentUsed")
        try:
            float(api_percent)
            api = percent_window(api_percent, end, mins, default_used=0.0)
        except (TypeError, ValueError):
            api = None
        included = percent_window(cursor_models_percent, end, mins, default_used=0.0) or {}
        remaining_label = None
        if remaining_cents is not None and remaining_cents > 0:
            remaining_label = format_cents_left(remaining_cents)
        else:
            remaining_label = f"{round(included.get('remainingPercent') or 0)}% left"
        return {
            "planType": plan_type,
            "included": included,
            "api": api,
            "remainingLabel": remaining_label,
            "isFree": is_free,
            "layout": "included-api" if api else "included",
        }

    bucket = pick_request_bucket(request_usage)
    if bucket:
        maximum = float(bucket.get("maxRequestUsage") or 0)
        used = float(bucket.get("numRequests") or 0)
        start = to_epoch_seconds(request_usage.get("startOfMonth") if isinstance(request_usage, dict) else None)
        return {
            "planType": plan_type,
            "included": percent_window((used / maximum) * 100.0 if maximum > 0 else 0, month_after(start), MONTHLY_MINS),
            "api": None,
            "remainingLabel": format_requests_left(maximum - used),
            "isFree": is_free,
            "layout": "requests",
        }

    return {
        "planType": plan_type,
        "included": None,
        "api": None,
        "remainingLabel": None,
        "isFree": is_free,
        "layout": "included",
    }


def prettify_tier(raw: Any) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.startswith("default_"):
        text = text[len("default_") :]
    if text.startswith("claude_"):
        text = text[len("claude_") :]
    return text.replace("_", " ")


def window_from(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    return percent_window(
        value.get("utilization", value.get("percent", value.get("usedPercent"))),
        value.get("resets_at", value.get("resetsAt")),
        default_used=None,
    )


def normalize_claude_usage(payload: Any = None, plan: Any = None) -> dict:
    payload = payload or {}
    plan = plan or {}
    five_hour = window_from(payload.get("five_hour"))
    weekly = window_from(payload.get("seven_day"))
    limits = payload.get("limits") if isinstance(payload.get("limits"), list) else []
    if not five_hour:
        five_hour = window_from(next((entry for entry in limits if isinstance(entry, dict) and entry.get("kind") == "session"), None))
    if not weekly:
        weekly = window_from(next((entry for entry in limits if isinstance(entry, dict) and entry.get("kind") == "weekly_all"), None))
    plan_type = prettify_tier(plan.get("rateLimitTier") or plan.get("subscriptionType") or payload.get("rate_limit_tier"))
    return {"planType": plan_type, "fiveHour": five_hour, "weekly": weekly}


def _normalize_rate_window(window: Any) -> dict | None:
    if not isinstance(window, dict):
        return None
    try:
        duration = float(window.get("windowDurationMins"))
    except (TypeError, ValueError):
        return None
    used = clamp_percent(window.get("usedPercent"), default=0.0) or 0.0
    resets = window.get("resetsAt")
    try:
        resets_at = float(resets)
    except (TypeError, ValueError):
        resets_at = None
    return {
        "usedPercent": used,
        "remainingPercent": 100.0 - used,
        "windowDurationMins": duration,
        "resetsAt": resets_at,
    }


def _window_kind(window: dict | None) -> str | None:
    if not window:
        return None
    duration = window.get("windowDurationMins")
    if duration == FIVE_HOUR_MINS:
        return "fiveHour"
    if duration == WEEKLY_MINS:
        return "weekly"
    if isinstance(duration, (int, float)) and duration >= MONTHLY_MIN_MINS:
        return "monthly"
    return None


def normalize_rate_limits(payload: Any = None) -> dict:
    payload = payload or {}
    bucket = None
    if isinstance(payload.get("rateLimitsByLimitId"), dict):
        bucket = payload["rateLimitsByLimitId"].get("codex")
    if bucket is None:
        bucket = payload.get("rateLimits")
    if not isinstance(bucket, dict):
        return {"planType": None, "fiveHour": None, "weekly": None, "monthly": None, "isFree": False}
    windows = [_normalize_rate_window(value) for value in bucket.values()]
    windows = [window for window in windows if window]
    def find(kind: str) -> dict | None:
        return next((window for window in windows if _window_kind(window) == kind), None)
    plan_type = bucket.get("planType")
    return {
        "planType": plan_type,
        "fiveHour": find("fiveHour"),
        "weekly": find("weekly"),
        "monthly": find("monthly"),
        "isFree": is_codex_free_plan(plan_type if isinstance(plan_type, str) else None),
    }


def clamp_fraction(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return min(1.0, max(0.0, number))


def normalize_antigravity_usage(snapshot: Any = None) -> dict:
    snapshot = snapshot or {}
    windows = []
    for group in snapshot.get("groups") or []:
        if not isinstance(group, dict):
            continue
        for bucket in group.get("buckets") or []:
            if not isinstance(bucket, dict):
                continue
            remaining = clamp_fraction(bucket.get("remainingFraction"))
            reported_used = clamp_fraction(bucket.get("usedFraction"))
            if bucket.get("available") is True:
                used = 0.0
            else:
                used = reported_used if reported_used is not None else (None if remaining is None else 1.0 - remaining)
            if used is None:
                continue
            windows.append(
                {
                    "group": group.get("name") or "Models",
                    "kind": bucket.get("kind"),
                    "label": bucket.get("label"),
                    "modelId": bucket.get("modelId") or bucket.get("model_id"),
                    "usedPercent": used * 100.0,
                    "remainingPercent": 100.0 - used * 100.0,
                    "resetsAt": to_epoch_seconds(bucket.get("resetAt")),
                }
            )
    latest = pick_latest_antigravity_window(windows)
    used_percent = latest["usedPercent"] if latest else None
    return {
        "planType": snapshot.get("tier"),
        "account": snapshot.get("account"),
        "source": snapshot.get("source"),
        "usedPercent": used_percent,
        "windows": windows,
    }


def needs_login(message: str, extra: str = "") -> bool:
    text = f"{message} {extra}".lower()
    return any(
        token in text
        for token in (
            "unauthorized",
            "unauthenticated",
            "login",
            "not logged",
            "credential",
            "not found",
            "enoent",
            "winerror 2",
        )
    )

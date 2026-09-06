from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import parse_env_text
from services.throttle.display import (
    format_cents_left,
    limits_for_provider,
    normalize_antigravity_usage,
    normalize_claude_usage,
    normalize_cursor_usage,
    normalize_rate_limits,
    prettify_tier,
    to_epoch_seconds,
    used_percent_for_provider,
)


class CursorUsageTests(unittest.TestCase):
    def test_cycle_timestamps_and_dollars(self) -> None:
        self.assertEqual(to_epoch_seconds("1771077734000"), 1771077734)
        self.assertEqual(
            to_epoch_seconds("2026-03-01T00:00:00.000Z"),
            int(datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp()),
        )
        self.assertEqual(format_cents_left(16778), "$168 left")
        self.assertEqual(format_cents_left(850), "$8.50 left")
        self.assertEqual(format_cents_left(2400), "$24 left")

    def test_cursor_models_and_other_models(self) -> None:
        result = normalize_cursor_usage(
            usage={
                "billingCycleStart": "1768399334000",
                "billingCycleEnd": "1771077734000",
                "planUsage": {
                    "includedSpend": 23222,
                    "remaining": 16778,
                    "limit": 40000,
                    "autoPercentUsed": 13.2,
                    "apiPercentUsed": 100,
                    "totalPercentUsed": 17.4,
                },
            },
            plan_info={"planInfo": {"planName": "Pro", "includedAmountCents": 40000}},
            membership_type="pro",
        )
        self.assertEqual(result["planType"], "Pro")
        self.assertEqual(result["layout"], "included-api")
        self.assertEqual(result["remainingLabel"], "$168 left")
        self.assertEqual(result["included"]["usedPercent"], 13.2)
        self.assertEqual(result["included"]["remainingPercent"], 86.8)
        self.assertEqual(result["included"]["resetsAt"], 1771077734)
        self.assertEqual(result["api"]["usedPercent"], 100)
        self.assertEqual(result["api"]["remainingPercent"], 0)

    def test_missing_limit_hides_api_tile(self) -> None:
        result = normalize_cursor_usage(
            plan_info={
                "planInfo": {
                    "planName": "Ultra",
                    "includedAmountCents": 40000,
                    "billingCycleEnd": "1771077734000",
                }
            },
            usage={
                "billingCycleStart": "1768399334000",
                "planUsage": {"includedSpend": 10000, "totalPercentUsed": 25},
            },
        )
        self.assertEqual(result["planType"], "Ultra")
        self.assertEqual(result["layout"], "included")
        self.assertIsNone(result["api"])
        self.assertEqual(result["remainingLabel"], "$300 left")
        self.assertEqual(result["included"]["usedPercent"], 25)

    def test_request_bucket_fallback(self) -> None:
        result = normalize_cursor_usage(
            membership_type="enterprise",
            request_usage={
                "gpt-4": {"numRequests": 150, "maxRequestUsage": 500},
                "startOfMonth": "2026-03-01T00:00:00.000Z",
            },
        )
        self.assertEqual(result["layout"], "requests")
        self.assertEqual(result["remainingLabel"], "350 left")
        self.assertEqual(result["included"]["usedPercent"], 30)
        self.assertEqual(result["included"]["remainingPercent"], 70)
        self.assertEqual(
            result["included"]["resetsAt"],
            int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp()),
        )

    def test_exhausted_spend_uses_remaining_percent(self) -> None:
        result = normalize_cursor_usage(
            plan_info={"planInfo": {"planName": "Pro"}},
            usage={
                "billingCycleEnd": "1771077734000",
                "planUsage": {
                    "includedSpend": 20000,
                    "remaining": 0,
                    "limit": 20000,
                    "apiPercentUsed": 95,
                    "totalPercentUsed": 79,
                },
            },
        )
        self.assertEqual(result["remainingLabel"], "21% left")
        self.assertEqual(result["included"]["remainingPercent"], 21)

    def test_empty_cursor_payload(self) -> None:
        result = normalize_cursor_usage(membership_type="free")
        self.assertEqual(result["planType"], "free")
        self.assertTrue(result["isFree"])
        self.assertIsNone(result["included"])
        self.assertIsNone(result["api"])


class ClaudeUsageTests(unittest.TestCase):
    def test_oauth_windows(self) -> None:
        result = normalize_claude_usage(
            {
                "five_hour": {"utilization": 34, "resets_at": "2026-02-06T22:00:00+00:00"},
                "seven_day": {"utilization": 12, "resets_at": "2026-02-12T20:00:00+00:00"},
            },
            {"rateLimitTier": "default_claude_max_5x"},
        )
        self.assertEqual(result["planType"], "max 5x")
        self.assertEqual(result["fiveHour"]["usedPercent"], 34)
        self.assertEqual(result["fiveHour"]["remainingPercent"], 66)
        self.assertEqual(result["weekly"]["usedPercent"], 12)
        self.assertEqual(
            result["fiveHour"]["resetsAt"],
            int(datetime(2026, 2, 6, 22, tzinfo=timezone.utc).timestamp()),
        )

    def test_limits_array_fallback(self) -> None:
        result = normalize_claude_usage(
            {
                "limits": [
                    {"kind": "session", "percent": 41, "resets_at": "2026-08-31T18:00:00Z"},
                    {"kind": "weekly_all", "percent": 9, "resets_at": "2026-09-06T18:00:00Z"},
                ]
            }
        )
        self.assertEqual(result["fiveHour"]["usedPercent"], 41)
        self.assertEqual(result["weekly"]["usedPercent"], 9)

    def test_empty_windows(self) -> None:
        result = normalize_claude_usage({})
        self.assertIsNone(result["fiveHour"])
        self.assertIsNone(result["weekly"])
        self.assertEqual(prettify_tier("default_claude_max_20x"), "max 20x")


class CodexUsageTests(unittest.TestCase):
    def test_window_kinds(self) -> None:
        result = normalize_rate_limits(
            {
                "rateLimits": {
                    "planType": "plus",
                    "primary": {"usedPercent": 61, "windowDurationMins": 10080, "resetsAt": 2000},
                    "secondary": {"usedPercent": 24, "windowDurationMins": 300, "resetsAt": 1500},
                }
            }
        )
        self.assertEqual(result["planType"], "plus")
        self.assertEqual(result["fiveHour"]["usedPercent"], 24)
        self.assertEqual(result["weekly"]["remainingPercent"], 39)

    def test_free_monthly(self) -> None:
        result = normalize_rate_limits(
            {
                "rateLimits": {
                    "planType": "free",
                    "primary": {"usedPercent": 33, "windowDurationMins": 43200, "resetsAt": 2000000},
                    "secondary": None,
                }
            }
        )
        self.assertTrue(result["isFree"])
        self.assertEqual(result["monthly"]["windowDurationMins"], 43200)
        self.assertEqual(result["monthly"]["remainingPercent"], 67)
        self.assertIsNone(result["fiveHour"])
        self.assertIsNone(result["weekly"])


class AntigravityUsageTests(unittest.TestCase):
    def test_groups(self) -> None:
        result = normalize_antigravity_usage(
            {
                "account": "dev@example.com",
                "tier": "Google AI Pro",
                "source": "api",
                "groups": [
                    {
                        "name": "Gemini models",
                        "buckets": [
                            {
                                "kind": "model",
                                "label": "Gemini 2.0 Flash",
                                "remainingFraction": 0.92,
                                "usedFraction": 0.08,
                                "resetAt": "2026-09-06T18:00:00Z",
                            },
                            {
                                "kind": "model",
                                "label": "Gemini 2.5 Pro",
                                "modelId": "gemini-2.5-pro",
                                "remainingFraction": 0.4,
                                "usedFraction": 0.6,
                                "resetAt": "2026-08-31T18:00:00Z",
                            },
                            {
                                "kind": "model",
                                "label": "Gemini 2.5 Flash",
                                "remainingFraction": 0.1,
                                "usedFraction": 0.9,
                            },
                        ],
                    }
                ],
            }
        )
        self.assertEqual(result["planType"], "Google AI Pro")
        self.assertEqual(result["usedPercent"], 60)
        self.assertEqual(result["windows"][0]["usedPercent"], 8)
        self.assertEqual(result["windows"][1]["remainingPercent"], 40)
        rows = limits_for_provider("antigravity", result)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "Gemini 2.5 Pro")
        self.assertEqual(rows[0]["used_percent"], 60)

    def test_available_bucket(self) -> None:
        self.assertEqual(
            normalize_antigravity_usage({"groups": [{"name": "Models", "buckets": [{"available": True}]}]})["usedPercent"],
            0,
        )
        self.assertIsNone(normalize_antigravity_usage({"groups": []})["usedPercent"])


class EnvFileTests(unittest.TestCase):
    def test_parse_env_text(self) -> None:
        parsed = parse_env_text(
            "AGY_OAUTH_CLIENT_ID=example-client.apps.example.test\n"
            "AGY_OAUTH_CLIENT_SECRET='example-secret'\n"
            "# comment\n"
            "EMPTY=\n"
        )
        self.assertEqual(parsed["AGY_OAUTH_CLIENT_ID"], "example-client.apps.example.test")
        self.assertEqual(parsed["AGY_OAUTH_CLIENT_SECRET"], "example-secret")


class DisplayTests(unittest.TestCase):
    def test_used_percent(self) -> None:
        self.assertEqual(
            used_percent_for_provider("cursor", {"included": {"usedPercent": 50}, "api": {"usedPercent": 90}}),
            50,
        )
        self.assertEqual(
            used_percent_for_provider("claude", {"fiveHour": {"usedPercent": 34}, "weekly": {"usedPercent": 12}}),
            34,
        )
        self.assertEqual(
            used_percent_for_provider(
                "codex",
                {"isFree": True, "monthly": {"usedPercent": 22}, "fiveHour": {"usedPercent": 80}},
            ),
            22,
        )
        self.assertEqual(used_percent_for_provider("antigravity", {"usedPercent": 42.5}), 42.5)
        self.assertEqual(
            used_percent_for_provider(
                "antigravity",
                {
                    "usedPercent": 90,
                    "windows": [
                        {"label": "Gemini 2.5 Flash", "usedPercent": 90},
                        {"label": "Gemini 2.5 Pro", "usedPercent": 12},
                    ],
                },
            ),
            12,
        )

    def test_limit_rows(self) -> None:
        rows = limits_for_provider(
            "claude",
            {"fiveHour": {"usedPercent": 10, "resetsAt": None}, "weekly": {"usedPercent": 20}},
        )
        self.assertEqual(rows[0]["label"], "Current session")
        self.assertEqual(rows[1]["label"], "All models")


if __name__ == "__main__":
    unittest.main()

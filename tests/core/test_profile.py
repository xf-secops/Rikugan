"""Tests for rikugan.core.profile — analysis profiles."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tests.mocks.ida_mock import install_ida_mocks
install_ida_mocks()

from rikugan.core.profile import (
    AnalysisProfile,
    DEFAULT_PROFILE,
    IOC_FILTER_CATEGORIES,
    PRIVATE_PROFILE,
    _BUILTIN_PROFILES,
    get_profile,
    list_profiles,
)


class TestBuiltinProfiles(unittest.TestCase):
    def test_default_profile_exists(self):
        self.assertEqual(DEFAULT_PROFILE.name, "default")
        self.assertTrue(DEFAULT_PROFILE.builtin)
        self.assertFalse(DEFAULT_PROFILE.hide_binary_metadata)
        self.assertFalse(DEFAULT_PROFILE.has_any_ioc_filter)

    def test_private_profile_exists(self):
        self.assertEqual(PRIVATE_PROFILE.name, "private")
        self.assertTrue(PRIVATE_PROFILE.builtin)
        self.assertTrue(PRIVATE_PROFILE.hide_binary_metadata)
        self.assertTrue(PRIVATE_PROFILE.has_any_ioc_filter)
        self.assertTrue(PRIVATE_PROFILE.singular_analysis)

    def test_private_profile_all_ioc_filters_enabled(self):
        """PRIVATE_PROFILE should have ALL IOC filter categories enabled."""
        for key in IOC_FILTER_CATEGORIES:
            self.assertTrue(
                PRIVATE_PROFILE.ioc_filters.get(key, False),
                f"Expected IOC filter '{key}' to be enabled in PRIVATE_PROFILE",
            )

    def test_builtin_profiles_dict(self):
        self.assertIn("default", _BUILTIN_PROFILES)
        self.assertIn("private", _BUILTIN_PROFILES)


class TestToFromDict(unittest.TestCase):
    def test_round_trip(self):
        """to_dict/from_dict round-trip preserves all fields."""
        ioc_filters = {"hashes": True, "ipv4": True, "domains": False}
        custom_rules = [
            {"name": "test-rule", "pattern": "secret", "is_regex": False, "replacement": "[REDACTED]"}
        ]
        profile = AnalysisProfile(
            name="test",
            description="Test profile",
            denied_tools=["tool_a", "tool_b"],
            denied_functions=["func_x"],
            custom_filters=["filter1"],
            hide_binary_metadata=True,
            ioc_filters=ioc_filters,
            custom_filter_rules=custom_rules,
            singular_analysis=True,
        )
        d = profile.to_dict()
        restored = AnalysisProfile.from_dict(d)

        self.assertEqual(restored.name, "test")
        self.assertEqual(restored.description, "Test profile")
        self.assertEqual(restored.denied_tools, ["tool_a", "tool_b"])
        self.assertEqual(restored.denied_functions, ["func_x"])
        self.assertEqual(restored.custom_filters, ["filter1"])
        self.assertTrue(restored.hide_binary_metadata)
        self.assertEqual(restored.ioc_filters, ioc_filters)
        self.assertEqual(restored.custom_filter_rules, custom_rules)
        self.assertTrue(restored.singular_analysis)

    def test_ioc_filters_round_trip(self):
        """ioc_filters dict survives serialization."""
        filters = {k: (i % 2 == 0) for i, k in enumerate(IOC_FILTER_CATEGORIES)}
        profile = AnalysisProfile(name="rt", ioc_filters=filters)
        d = profile.to_dict()
        restored = AnalysisProfile.from_dict(d)
        self.assertEqual(restored.ioc_filters, filters)

    def test_custom_filter_rules_round_trip(self):
        """custom_filter_rules survive serialization."""
        rules = [
            {"name": "r1", "pattern": r"sk-[a-zA-Z0-9]+", "is_regex": True, "replacement": "[KEY]"},
            {"name": "r2", "pattern": "DESKTOP-HOST", "is_regex": False, "replacement": "[HOST]"},
        ]
        profile = AnalysisProfile(name="cr", custom_filter_rules=rules)
        d = profile.to_dict()
        restored = AnalysisProfile.from_dict(d)
        self.assertEqual(restored.custom_filter_rules, rules)

    def test_backward_compat_filter_iocs_in_data(self):
        """Old config with filter_iocs_in_data=True should migrate to all ioc_filters."""
        d = {"name": "legacy", "filter_iocs_in_data": True}
        profile = AnalysisProfile.from_dict(d)
        for key in IOC_FILTER_CATEGORIES:
            self.assertTrue(
                profile.ioc_filters.get(key, False),
                f"Expected '{key}' to be True after backward-compat migration",
            )
        self.assertTrue(profile.has_any_ioc_filter)

    def test_backward_compat_filter_iocs_false(self):
        """Old config with filter_iocs_in_data=False → no ioc_filters."""
        d = {"name": "legacy-off", "filter_iocs_in_data": False}
        profile = AnalysisProfile.from_dict(d)
        self.assertFalse(profile.has_any_ioc_filter)

    def test_to_dict_excludes_builtin(self):
        """builtin flag should not be persisted."""
        profile = AnalysisProfile(name="x", builtin=True)
        d = profile.to_dict()
        self.assertNotIn("builtin", d)

    def test_from_dict_ignores_unknown_keys(self):
        """Unknown keys in dict should be silently ignored."""
        d = {"name": "test", "unknown_field": True, "description": "desc"}
        profile = AnalysisProfile.from_dict(d)
        self.assertEqual(profile.name, "test")
        self.assertEqual(profile.description, "desc")

    def test_from_dict_defaults(self):
        """Missing fields get dataclass defaults."""
        d = {"name": "minimal"}
        profile = AnalysisProfile.from_dict(d)
        self.assertEqual(profile.name, "minimal")
        self.assertFalse(profile.hide_binary_metadata)
        self.assertEqual(profile.denied_tools, [])
        self.assertEqual(profile.ioc_filters, {})
        self.assertEqual(profile.custom_filter_rules, [])


class TestHasAnyIocFilter(unittest.TestCase):
    def test_no_filters(self):
        profile = AnalysisProfile(name="empty")
        self.assertFalse(profile.has_any_ioc_filter)

    def test_all_false(self):
        profile = AnalysisProfile(name="off", ioc_filters={k: False for k in IOC_FILTER_CATEGORIES})
        self.assertFalse(profile.has_any_ioc_filter)

    def test_one_true(self):
        profile = AnalysisProfile(name="one", ioc_filters={"hashes": True})
        self.assertTrue(profile.has_any_ioc_filter)

    def test_filter_iocs_in_data_compat_property(self):
        """The backward-compat filter_iocs_in_data property should mirror has_any_ioc_filter."""
        profile = AnalysisProfile(name="compat", ioc_filters={"urls": True})
        self.assertTrue(profile.filter_iocs_in_data)


class TestGetProfile(unittest.TestCase):
    def test_get_builtin_default(self):
        profile = get_profile("default")
        self.assertEqual(profile.name, "default")
        self.assertTrue(profile.builtin)

    def test_get_builtin_private(self):
        profile = get_profile("private")
        self.assertEqual(profile.name, "private")
        self.assertTrue(profile.hide_binary_metadata)

    def test_get_custom_profile(self):
        custom = {
            "my-profile": {
                "name": "my-profile",
                "description": "Custom",
                "hide_binary_metadata": True,
            }
        }
        profile = get_profile("my-profile", custom)
        self.assertEqual(profile.name, "my-profile")
        self.assertEqual(profile.description, "Custom")
        self.assertTrue(profile.hide_binary_metadata)

    def test_unknown_profile_falls_back_to_default(self):
        profile = get_profile("nonexistent")
        self.assertEqual(profile.name, "default")
        self.assertTrue(profile.builtin)

    def test_unknown_with_custom_still_falls_back(self):
        custom = {"other": {"name": "other"}}
        profile = get_profile("nonexistent", custom)
        self.assertEqual(profile.name, "default")


class TestListProfiles(unittest.TestCase):
    def test_list_builtins_only(self):
        profiles = list_profiles()
        names = [p.name for p in profiles]
        self.assertIn("default", names)
        self.assertIn("private", names)

    def test_list_with_custom(self):
        custom = {
            "custom-1": {"name": "custom-1", "description": "First"},
            "custom-2": {"name": "custom-2", "description": "Second"},
        }
        profiles = list_profiles(custom)
        names = [p.name for p in profiles]
        self.assertIn("default", names)
        self.assertIn("private", names)
        self.assertIn("custom-1", names)
        self.assertIn("custom-2", names)

    def test_custom_does_not_override_builtin(self):
        """Custom profile named 'default' should not replace the builtin."""
        custom = {"default": {"name": "default", "description": "Fake"}}
        profiles = list_profiles(custom)
        default_profiles = [p for p in profiles if p.name == "default"]
        # Should only have the builtin, not the custom
        self.assertEqual(len(default_profiles), 1)
        self.assertTrue(default_profiles[0].builtin)


if __name__ == "__main__":
    unittest.main()

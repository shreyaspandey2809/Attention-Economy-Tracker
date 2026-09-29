import pytest

from attention_tracker.schema.app_metadata import AppCategory
from attention_tracker.schema.taxonomy_loader import (
    TaxonomyLoadError,
    TaxonomyLoader,
    DEFAULT_TAXONOMY_PATH,
)


@pytest.fixture(scope="module")
def loader() -> TaxonomyLoader:
    return TaxonomyLoader()


class TestTaxonomyLoader:
    def test_loads_default_taxonomy_file(self, loader: TaxonomyLoader):
        assert DEFAULT_TAXONOMY_PATH.exists()
        assert len(loader) >= 40  # spec called for ~40-60 seed apps

    def test_known_app_resolves_correct_category(self, loader: TaxonomyLoader):
        entry = loader.lookup("com.instagram.android")
        assert entry.category == AppCategory.ADDICTIVE
        assert entry.display_name == "Instagram"
        assert entry.is_user_override is False

    def test_all_categories_represented(self, loader: TaxonomyLoader):
        categories = {loader.lookup(pkg).category for pkg in loader._entries}
        assert categories == {
            AppCategory.ADDICTIVE,
            AppCategory.ENTERTAINMENT,
            AppCategory.COMMUNICATION,
            AppCategory.PRODUCTIVE,
            AppCategory.UTILITY,
        }

    def test_unknown_package_falls_back_gracefully(self, loader: TaxonomyLoader):
        entry = loader.lookup("com.some.unlisted.app")
        assert entry.category == AppCategory.UNKNOWN
        assert entry.package_name == "com.some.unlisted.app"
        # unknown packages don't raise — this is an expected runtime
        # case once real device data (M9) arrives, not an error
        assert "com.some.unlisted.app" not in loader

    def test_contains_operator(self, loader: TaxonomyLoader):
        assert "com.whatsapp" in loader
        assert "com.totally.made.up" not in loader

    def test_missing_file_raises(self, tmp_path):
        missing = tmp_path / "does_not_exist.yaml"
        with pytest.raises(TaxonomyLoadError, match="not found"):
            TaxonomyLoader(path=missing)

    def test_malformed_file_missing_apps_key_raises(self, tmp_path):
        bad_file = tmp_path / "bad_taxonomy.yaml"
        bad_file.write_text("not_apps_key:\n  foo: bar\n")
        with pytest.raises(TaxonomyLoadError, match="apps"):
            TaxonomyLoader(path=bad_file)

    def test_malformed_entry_invalid_category_raises(self, tmp_path):
        bad_file = tmp_path / "bad_category.yaml"
        bad_file.write_text(
            "apps:\n"
            "  com.example.app:\n"
            "    display_name: Example\n"
            "    category: NOT_A_REAL_CATEGORY\n"
        )
        with pytest.raises(TaxonomyLoadError, match="com.example.app"):
            TaxonomyLoader(path=bad_file)

    def test_malformed_entry_missing_display_name_raises(self, tmp_path):
        bad_file = tmp_path / "missing_field.yaml"
        bad_file.write_text(
            "apps:\n  com.example.app:\n    category: UTILITY\n"
        )
        with pytest.raises(TaxonomyLoadError):
            TaxonomyLoader(path=bad_file)

class TestExtendedTaxonomy:
    def test_default_loader_is_seed_only_and_ignores_nothing(self):
        from attention_tracker.schema.taxonomy_loader import TaxonomyLoader

        default = TaxonomyLoader()
        assert "com.phonepe.app" not in default
        assert not default.is_ignored("com.android.launcher3")

    def test_extended_adds_real_world_apps(self):
        from attention_tracker.schema.taxonomy_loader import TaxonomyLoader

        tax = TaxonomyLoader(include_extended=True)
        assert len(tax) > len(TaxonomyLoader())
        assert tax.lookup("com.phonepe.app").category == AppCategory.UTILITY
        assert tax.lookup("com.sharechat.android").category == AppCategory.ADDICTIVE
        assert tax.lookup("com.leetcode.android").category == AppCategory.PRODUCTIVE

    def test_extended_never_overrides_a_seed_category(self):
        from attention_tracker.schema.taxonomy_loader import TaxonomyLoader

        seed = TaxonomyLoader()
        merged = TaxonomyLoader(include_extended=True)
        for pkg, entry in seed._entries.items():  # noqa: SLF001
            assert merged.lookup(pkg).category == entry.category

    def test_system_surfaces_are_ignored(self):
        from attention_tracker.schema.taxonomy_loader import TaxonomyLoader

        tax = TaxonomyLoader(include_extended=True)
        for pkg in (
            "com.android.launcher3",
            "com.android.systemui",
            "com.google.android.inputmethod.latin",
            "com.google.android.dialer",
        ):
            assert tax.is_ignored(pkg), pkg

    def test_real_apps_are_not_ignored(self):
        from attention_tracker.schema.taxonomy_loader import TaxonomyLoader

        tax = TaxonomyLoader(include_extended=True)
        assert not tax.is_ignored("com.instagram.android")
        assert not tax.is_ignored("com.phonepe.app")

    def test_no_package_is_both_categorized_and_ignored(self):
        from attention_tracker.schema.taxonomy_loader import TaxonomyLoader

        tax = TaxonomyLoader(include_extended=True)
        assert not (tax._ignored & set(tax._entries))  # noqa: SLF001

    def test_clash_between_apps_and_ignored_is_rejected(self, tmp_path):
        from attention_tracker.schema.taxonomy_loader import (
            TaxonomyLoader,
            TaxonomyLoadError,
        )

        bad = tmp_path / "ext.yaml"
        bad.write_text(
            "apps:\n  com.foo: {display_name: Foo, category: UTILITY}\n"
            "ignored_packages:\n  - com.foo\n"
        )
        with pytest.raises(TaxonomyLoadError, match="both categorized and ignored"):
            TaxonomyLoader(include_extended=True, extended_path=bad)

    def test_missing_extended_file_raises(self, tmp_path):
        from attention_tracker.schema.taxonomy_loader import (
            TaxonomyLoader,
            TaxonomyLoadError,
        )

        with pytest.raises(TaxonomyLoadError, match="not found"):
            TaxonomyLoader(include_extended=True, extended_path=tmp_path / "nope.yaml")

    def test_realistic_indian_android_coverage_is_high(self):
        from attention_tracker.schema.taxonomy_loader import TaxonomyLoader

        tax = TaxonomyLoader(include_extended=True)
        realistic = [
            "com.whatsapp", "com.instagram.android", "com.google.android.youtube",
            "in.startv.hotstar", "com.phonepe.app", "net.one97.paytm",
            "com.application.zomato", "in.swiggy.android", "com.jio.jiotv",
            "com.mxtech.videoplayer.ad", "com.google.android.apps.nbu.paisa.user",
            "com.sharechat.android", "in.mohalla.video", "com.truecaller",
            "com.android.vending", "com.miui.gallery", "com.myntra.android",
            "com.linkedin.android", "com.spotify.music", "com.netflix.mediaclient",
        ]
        known = sum(1 for p in realistic if p in tax)
        assert known / len(realistic) >= 0.9, f"only {known}/{len(realistic)} known"
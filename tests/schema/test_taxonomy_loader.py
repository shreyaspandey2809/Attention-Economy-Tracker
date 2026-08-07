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
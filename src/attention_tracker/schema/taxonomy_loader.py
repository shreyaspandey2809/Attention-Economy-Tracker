"""
TaxonomyLoader — reads config/app_taxonomy.yaml, validates every row
through AppMetadataEntry, and exposes a lookup with a defined fallback
for unknown packages (AppCategory.UNKNOWN, not a KeyError).

Kept intentionally dumb this week: no caching strategy, no hot-reload,
no override persistence. Per the hardcode-first approach (Ch. 9.2),
this stays a straightforward "load once, look up" helper until the API
layer (M8) needs something more dynamic (e.g. a POST endpoint that
writes user overrides), at which point this gets a storage-backed
sibling rather than being complicated in place.
"""

from pathlib import Path

import yaml

from attention_tracker.schema.app_metadata import AppCategory
from attention_tracker.schema.app_metadata_entry import AppMetadataEntry

DEFAULT_TAXONOMY_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "app_taxonomy.yaml"
)


class TaxonomyLoadError(ValueError):
    """Raised when the taxonomy file is missing, malformed, or has
    an entry that fails AppMetadataEntry validation."""


class TaxonomyLoader:
    def __init__(self, path: Path | str = DEFAULT_TAXONOMY_PATH):
        self.path = Path(path)
        self._entries: dict[str, AppMetadataEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            raise TaxonomyLoadError(f"taxonomy file not found at {self.path}")

        with self.path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        if not raw or "apps" not in raw:
            raise TaxonomyLoadError(
                f"taxonomy file {self.path} is missing top-level 'apps' key"
            )

        for package_name, fields in raw["apps"].items():
            try:
                entry = AppMetadataEntry(
                    package_name=package_name,
                    display_name=fields["display_name"],
                    category=fields["category"],
                )
            except Exception as exc:  # noqa: BLE001 — re-raised with context below
                raise TaxonomyLoadError(
                    f"invalid taxonomy entry for '{package_name}': {exc}"
                ) from exc
            self._entries[package_name] = entry

    def lookup(self, package_name: str) -> AppMetadataEntry:
        """Return the known entry, or a synthesized UNKNOWN entry if
        the package isn't in the taxonomy. Never raises for a missing
        package — unknown apps are an expected runtime case (M9 real
        device data will surface packages the seed taxonomy has never
        seen), not an error condition.
        """
        if package_name in self._entries:
            return self._entries[package_name]
        return AppMetadataEntry(
            package_name=package_name,
            display_name=package_name,
            category=AppCategory.UNKNOWN,
        )

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, package_name: str) -> bool:
        return package_name in self._entries

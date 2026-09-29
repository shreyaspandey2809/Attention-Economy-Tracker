from pathlib import Path

import yaml

from attention_tracker.schema.app_metadata import AppCategory
from attention_tracker.schema.app_metadata_entry import AppMetadataEntry

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
DEFAULT_TAXONOMY_PATH = _CONFIG_DIR / "app_taxonomy.yaml"
EXTENDED_TAXONOMY_PATH = _CONFIG_DIR / "app_taxonomy_extended.yaml"


class TaxonomyLoadError(ValueError):
    """Raised when the taxonomy file is missing, malformed, or has
    an entry that fails AppMetadataEntry validation."""


class TaxonomyLoader:

    def __init__(
        self,
        path: Path | str = DEFAULT_TAXONOMY_PATH,
        include_extended: bool = False,
        extended_path: Path | str = EXTENDED_TAXONOMY_PATH,
    ):
        self.path = Path(path)
        self._entries: dict[str, AppMetadataEntry] = {}
        self._ignored: frozenset[str] = frozenset()
        self._load()
        if include_extended:
            self._load_extended(Path(extended_path))

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

    def _load_extended(self, path: Path) -> None:
        if not path.exists():
            raise TaxonomyLoadError(f"extended taxonomy file not found at {path}")

        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        for package_name, fields in (raw.get("apps") or {}).items():
            if package_name in self._entries:
                continue  # seed wins
            try:
                self._entries[package_name] = AppMetadataEntry(
                    package_name=package_name,
                    display_name=fields["display_name"],
                    category=fields["category"],
                )
            except Exception as exc:  # noqa: BLE001
                raise TaxonomyLoadError(
                    f"invalid extended taxonomy entry for '{package_name}': {exc}"
                ) from exc

        ignored = frozenset(raw.get("ignored_packages") or [])
        clash = ignored & set(self._entries)
        if clash:
            raise TaxonomyLoadError(
                f"packages cannot be both categorized and ignored: {sorted(clash)}"
            )
        self._ignored = ignored

    def is_ignored(self, package_name: str) -> bool:
        """True for system surfaces that should not be scored."""
        return package_name in self._ignored

    def lookup(self, package_name: str) -> AppMetadataEntry:
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
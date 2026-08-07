"""
AppMetadata — the resolved category + provenance for a given package.

A category can come from the seed taxonomy (config/app_taxonomy.yaml)
or from a user override (e.g. a future API endpoint letting someone
correct "this app is actually Productive for me"). is_user_override
lets the feature pipeline and any future UI distinguish "we guessed"
from "the user told us" without losing the original seed value.
"""

from pydantic import BaseModel, Field

from attention_tracker.schema.app_metadata import AppCategory


class AppMetadataEntry(BaseModel):
    package_name: str = Field(..., min_length=1, max_length=255)
    display_name: str = Field(..., min_length=1, max_length=255)
    category: AppCategory
    is_user_override: bool = False

    model_config = {"extra": "forbid"}

"""
AppMetadata — maps a package_name to a behavioral AppCategory.

Full model (with is_user_override, taxonomy source, etc.) lands in
Week 2 alongside the taxonomy loader. This week only defines the
AppCategory enum, since RawEvent's neighbors (Session, AppMetadata)
and the feature pipeline all need a stable reference to it.
"""

from enum import Enum


class AppCategory(str, Enum):
    PRODUCTIVE = "PRODUCTIVE"
    ADDICTIVE = "ADDICTIVE"
    ENTERTAINMENT = "ENTERTAINMENT"
    COMMUNICATION = "COMMUNICATION"
    UTILITY = "UTILITY"
    UNKNOWN = "UNKNOWN"

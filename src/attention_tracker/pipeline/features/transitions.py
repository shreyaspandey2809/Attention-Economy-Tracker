from attention_tracker.schema.session import Session
from attention_tracker.schema.taxonomy_loader import TaxonomyLoader
from attention_tracker.schema.app_metadata import AppCategory


def productive_interruption_rate(sessions: list[Session], taxonomy: TaxonomyLoader,) -> float:
    if not sessions:
        raise ValueError("productive_interruption_rate requires at least one session")

    eligible = [s for s in sessions if s.transition_from is not None]
    if not eligible:
        return 0.0

    interruptions = sum(
        1
        for s in eligible
        if taxonomy.lookup(s.transition_from).category == AppCategory.PRODUCTIVE
    )
    return interruptions / len(eligible)
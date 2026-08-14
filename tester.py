from datetime import datetime, timezone
from attention_tracker.synthetic.archetypes import BALANCED, DOOMSCROLLER
from attention_tracker.synthetic.generator import SyntheticEventGenerator

gen = SyntheticEventGenerator()
events = gen.generate(
    user_id="demo_user",
    profile=DOOMSCROLLER,
    start_date=datetime(2026, 8, 3, tzinfo=timezone.utc),
    num_days=7,
)
print(f"Generated {len(events)} events across 7 days")
for e in events[:10]:
    print(e)
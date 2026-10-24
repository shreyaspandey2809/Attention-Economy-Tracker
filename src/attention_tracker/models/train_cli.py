import argparse
from pathlib import Path

from attention_tracker.models.lightgbm_scorer import train_model
from attention_tracker.models.registry import default_registry_dir, save_model
from attention_tracker.models.synthetic_dataset import (
    SyntheticDatasetConfig,
    build_synthetic_distillation_dataset,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="registry directory")
    parser.add_argument("--seeds", type=int, default=20, help="users per archetype")
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    out = args.out or default_registry_dir()
    config = SyntheticDatasetConfig(seeds_per_archetype=args.seeds, num_days=args.days)
    dataset = build_synthetic_distillation_dataset(config)
    print(f"dataset: {len(dataset)} windows, {len(set(dataset.groups))} synthetic users")

    for kind in ("addiction", "distraction"):
        result = train_model(dataset, kind=kind, seed=args.seed)
        record = save_model(
            result,
            root=out,
            extra_meta={"seed": args.seed, "seeds_per_archetype": args.seeds, "num_days": args.days},
        )
        r2 = result.test_distillation.r_squared
        print(
            f"{kind}: saved {record.path} "
            f"(test R2 vs heuristic {r2:.3f}, {result.best_iteration} rounds)"
        )
    print("R2 measures how well a model reproduces its heuristic on synthetic users, not accuracy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
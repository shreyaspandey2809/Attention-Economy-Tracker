import math
from dataclasses import dataclass


def _ranks(values: list[float]) -> list[float]:
    """Average ranks (1-based), ties share the mean of their positions."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def pearson(x: list[float], y: list[float]) -> float | None:
    """Pearson r, or None when undefined (a constant input)."""
    if len(x) != len(y):
        raise ValueError("x and y must be the same length")
    n = len(x)
    if n < 2:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    return sxy / math.sqrt(sxx * syy)


def spearman(x: list[float], y: list[float]) -> float | None:
    """Spearman rank correlation with tie handling."""
    if len(x) != len(y):
        raise ValueError("x and y must be the same length")
    return pearson(_ranks(x), _ranks(y))


def bootstrap_ci(
    x: list[float],
    y: list[float],
    *,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float] | None:
    """Percentile bootstrap CI for Spearman rho, resampling PAIRS.

    With small pilot samples (tens of users) a point estimate alone is
    misleading; the interval is what should be reported."""
    import random

    n = len(x)
    if n < 3:
        return None
    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        r = spearman([x[i] for i in idx], [y[i] for i in idx])
        if r is not None:
            stats.append(r)
    if len(stats) < n_boot // 2:
        return None
    stats.sort()
    lo = stats[int((alpha / 2) * len(stats))]
    hi = stats[min(len(stats) - 1, int((1 - alpha / 2) * len(stats)))]
    return lo, hi


@dataclass(frozen=True)
class ValidityReport:
    n_users: int
    spearman_rho: float | None
    ci_low: float | None
    ci_high: float | None
    interpretation: str


# Below this many users a correlation is too unstable to interpret.
MIN_USERS_FOR_VALIDITY = 20


def score_vs_label_validity(
    user_scores: dict[str, float],
    user_labels: dict[str, float],
) -> ValidityReport:
    """Correlate a per-user usage score with a per-user SAS-SV total.

    Only users present in BOTH dicts are used. Pass one score per user
    (e.g. mean heuristic score over the observation period); do not
    pass per-day rows, or one person counts many times and inflates
    confidence.
    """
    common = sorted(set(user_scores) & set(user_labels))
    xs = [user_scores[u] for u in common]
    ys = [user_labels[u] for u in common]
    n = len(common)

    if n < MIN_USERS_FOR_VALIDITY:
        return ValidityReport(
            n_users=n,
            spearman_rho=spearman(xs, ys) if n >= 2 else None,
            ci_low=None,
            ci_high=None,
            interpretation=(
                f"Only {n} users with both a score and a label; need at "
                f"least {MIN_USERS_FOR_VALIDITY}. Any correlation shown is "
                "not interpretable."
            ),
        )

    rho = spearman(xs, ys)
    ci = bootstrap_ci(xs, ys)
    if rho is None or ci is None:
        return ValidityReport(n, rho, None, None, "Correlation undefined (constant input).")

    lo, hi = ci
    if lo > 0:
        text = (
            f"Score rank tracks SAS-SV rank (rho={rho:.2f}, 95% CI "
            f"[{lo:.2f}, {hi:.2f}] excludes 0). Supports, but does not "
            "prove, that the score measures something related to "
            "self-reported problematic use."
        )
    elif hi < 0:
        text = (
            f"Score rank is INVERSELY related to SAS-SV (rho={rho:.2f}, "
            f"95% CI [{lo:.2f}, {hi:.2f}]). The score is not measuring "
            "what it claims to."
        )
    else:
        text = (
            f"No detectable relationship (rho={rho:.2f}, 95% CI "
            f"[{lo:.2f}, {hi:.2f}] includes 0). The score is not shown to "
            "track self-reported problematic use in this sample."
        )
    return ValidityReport(n, rho, lo, hi, text)


def r_squared(y_true: list[float], y_pred: list[float]) -> float | None:
    if len(y_true) != len(y_pred):
        raise ValueError("y_true and y_pred must be the same length")
    n = len(y_true)
    if n < 2:
        return None
    mean = sum(y_true) / n
    ss_tot = sum((y - mean) ** 2 for y in y_true)
    if ss_tot == 0:
        return None
    ss_res = sum((y - p) ** 2 for y, p in zip(y_true, y_pred))
    return 1 - ss_res / ss_tot


@dataclass(frozen=True)
class DistillationReport:
    n_windows: int
    r_squared: float | None
    caveat: str


DISTILLATION_CAVEAT = (
    "This measures how well a model REPRODUCES the M4 heuristic on "
    "held-out users. The heuristic is a deterministic function of the "
    "model's inputs, so a high value is expected and says nothing about "
    "whether either one detects real problematic use. Do not report it "
    "as accuracy."
)


def distillation_report(y_heuristic: list[float], y_model: list[float]) -> DistillationReport:
    return DistillationReport(
        n_windows=len(y_heuristic),
        r_squared=r_squared(y_heuristic, y_model),
        caveat=DISTILLATION_CAVEAT,
    )
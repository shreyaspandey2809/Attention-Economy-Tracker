# Validation protocol

How this project finds out whether its score tracks anything real.

## Why a protocol is needed

Every score in the repo is computed from usage data alone. The M4
heuristic is a fixed formula of the engineered features, and M5 is
trained on that formula's output. A model trained this way can only
learn the formula: a plain linear regression on the heuristic's own
inputs already recovers it on held-out synthetic users (R² ≈ 0.94),
and gradient boosting will do better. High agreement with the
heuristic therefore says nothing about whether either one detects
problematic smartphone use.

The only thing that can answer that is an independent label: something
a person reported about themselves, collected separately from the
usage data.

## Instrument

Smartphone Addiction Scale - Short Version (SAS-SV), Kwon et al., 2013.

- 10 items, each 1-6 (strongly disagree to strongly agree)
- Total 10-60, higher means higher risk
- Published screening cut-offs: 31 (male), 33 (female), at or above
- Item wording is not reproduced in this repo. Use the instrument as
  published in the original paper.

Limits to state whenever a result is reported:

- The cut-offs were derived on Korean adolescents. Applying them to
  adult university students is an extrapolation. Report and analyse the
  continuous total; treat the binary flag as secondary.
- It is a screening questionnaire, not a clinical diagnosis.
- Self-report has its own biases (recall, social desirability).

Code: `src/attention_tracker/evaluation/labels.py`.

## Pilot design

1. **Participants.** 20 to 30 adult volunteers at minimum (the code
   refuses to interpret a correlation below 20 users). Recruit across
   usage levels, not only heavy users, or the label has no spread.
2. **Consent.** Written, informed, opt-in. State what is collected
   (app package names, session times, timezone offset), that nothing
   is collected without Usage Access permission being granted, and that
   they can withdraw and have their data deleted at any time.
3. **Pseudonymous ids.** The `user_id` in the usage data is the only
   link to the questionnaire. No names, phone numbers or contacts are
   stored next to it.
4. **Observation window.** At least 14 consecutive days of usage per
   participant, so weekend and weekday behavior are both seen.
5. **Questionnaire timing.** Administer the SAS-SV once, after the
   observation window, so answering it does not change behavior during
   the window.
6. **Ethics.** Get approval or written sign-off from the institution
   before collecting from anyone outside the team.

## Analysis

One score per user, not per day. Take each user's mean heuristic score
over the window, pair it with their SAS-SV total, and call
`evaluation.validation.score_vs_label_validity`.

It reports Spearman rank correlation with a 95% bootstrap interval
over resampled users, and states in plain words which of four cases
applies: too few users, a tracking relationship, no detectable
relationship, or an inverse relationship.

Decision rule, fixed before looking at data:

- Interval excludes 0 and rho is positive: the score is supported as
  related to self-reported problematic use. Say "supports", not
  "proves".
- Interval includes 0: the score is not shown to track the label. That
  is a real result; do not tune weights on the pilot sample until it
  goes away.
- Interval is entirely negative: the score is measuring something else.
  Revisit the feature design.

Weights may only be revised on a separate sample from the one used to
report validity, otherwise the reported correlation is inflated.

## What M5 is allowed to claim

- Trained on the heuristic: "a model that approximates the M4 heuristic".
  Report `evaluation.validation.distillation_report`, which carries its
  own caveat. Never call it accuracy.
- Trained on SAS-SV labels: only once the pilot exists. Evaluate on
  held-out users and report the same rank-correlation interval.

## Sequence input for M6

`pipeline/sequences.py` builds one ordered sequence per user per local
day across all apps, so the LSTM can use ordering. Its training target
must be chosen before M6 starts: either the heuristic (same caveat as
above) or a per-user SAS-SV total once labels exist.
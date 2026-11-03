# Voluntary independent researcher trial

This is an onboarding/usability dry run on public and synthetic demonstration data. It is not a request for a private dataset, a model-training artifact, an identity, or a contact address. There is no telemetry or automatic submission.

Ask a researcher who was not involved in building PrivateLabBench to follow [the walkthrough](../case_study.md) from a fresh Python 3.11 environment without maintainer assistance. Record both successful and unsuccessful attempts. Use anonymous labels such as `trial-01`; participation and every note are voluntary.

Use the version pinned in the walkthrough so results can be compared. Participants
may submit a short, redacted note in
[issue #47](https://github.com/dipeshbabu/private-lab-bench/issues/47); posting is
optional. Check the [findings](findings.md) for the current trial count. Do not
submit a complete run directory.

## What to try

1. Install from the documented checkout/constraints and run the complete case.
2. Find the candidate's public-control and synthetic-proxy outcomes.
3. Explain whether the candidate is better than the baseline and whether it meets the fixed acceptance requirements.
4. Verify a generated receipt with that run's public trust store.
5. Explain what verification established and what remains declared/unverified.
6. Identify which files could be shared and which must stay local.

## Optional redacted note template

```text
Trial label:
Not involved in package development: yes / no / prefer not to state
Broad environment (optional OS and Python version; no usernames or paths):
Minutes spent on setup:
Minutes to first valid result (or failure/stop point):
Completed without maintainer help: yes / no / stopped
What blocked or confused you:
Could you distinguish relative improvement from the failing quality gate:
What did trusted verification establish:
Which outputs would you share:
Did this answer an evaluation question beyond a metric value:
One suggested change:
Permission to quote these redacted notes anonymously: yes / no
```

Do not attach the output directory, private signing key, raw data, private model files, contact details, or full unredacted terminal logs. Redact identifiers, institution names, access tokens, and local paths from any example error. A short description is sufficient.

The maintainer should retain only voluntarily supplied redacted notes and aggregate timings/outcomes, report failures as well as successes, and record at least two concrete changes made in response to observed friction. Agent runs, automated CI environments, and the author's own reruns are not independent researcher trials.

# Example: catching an agent regression with `diff` and `check`

This example compares two versions of a simulated support agent. The candidate version has a
known, injected regression: on refund requests its planner re-checks the refund policy in a
loop, and the refund tool times out more often. The top-line success rate barely moves; the path
comparison shows what changed.

**The data is synthetic.** `simulate_agent.py` is a seeded simulator written for this example.
It shows what JourneyGraph reports for a regression whose cause is known in advance. It is not
evidence about any real system, and the numbers below say nothing about real agents.

## Run it

From this directory, with `journeygraph` 0.3.0 or later installed:

```bash
mkdir -p out
python simulate_agent.py baseline  out/baseline.jsonl
python simulate_agent.py candidate out/candidate.jsonl

journeygraph diff out/baseline.jsonl out/candidate.jsonl --output-dir out/diff
journeygraph check out/candidate.jsonl --rules rules.toml --baseline out/baseline.jsonl
```

The simulator uses only the standard library and fixed seeds, so every run writes the same
600 traces per version. Open `out/diff/diff.html` for the comparison report.

## What to expect

`journeygraph check` exits with code 5 and prints:

```text
PASS min_success_rate: success among known outcomes is 0.928333 (limit 0.85)
PASS max_error_event_rate: error events among events is 0.0176971 (limit 0.05)
PASS max_success_rate_drop: success among known outcomes dropped by 0.02 (limit 0.03)
FAIL max_error_event_rate_increase: error-event rate increased by 0.0119583 (limit 0.01)
PASS max_mean_cost_per_trace_increase: mean cost per trace increased by (relative) 0.0747896 (limit 0.15)
PASS forbid_new_categories: new categories: none
check: 5 of 6 rule(s) passed
```

The aggregate rules mostly pass: success drops from 94.8% to 92.8%, within the allowed 3
points, and mean cost per trace rises 7.5%, within the allowed 15%. Only the error-event rule
fails, and by a small margin.

The diff report shows where the change is:

| Observation | Baseline | Candidate |
| --- | --- | --- |
| `tool:refund_api` error rate | 9% | 30% |
| Traces that retry `tool:refund_api` | 9 | 41 |
| Traces with the loop `policy_check → planner → policy_check` | 0 | 91 |
| Distinct paths | 7 | 13 |

## Files

- `simulate_agent.py`: the simulator. The injected regression is marked with a comment.
- `rules.toml`: the thresholds and regression limits used by `journeygraph check`.

# Judge validation protocol — written 2026-10-13, BEFORE judge_cap_v2 was run

1. Labels (eval/labels_cap_70.json) frozen and hashed before any judge call. Revisions only in labels_cap_70_revisions.json, only for verifiable factual errors of mine, always disclosed.
2. judge_cap_v1 run on the DEV split. Disagreements read. One revision allowed (judge_cap_v2), from dev evidence only.
3. Choosing the prompt: the one with fewer natural-set disagreements on DEV (using the revised label); a tie goes to v1. Decided now, not after seeing v2.
4. The chosen prompt is frozen. The TEST split is then run ONCE per cell, 3 runs, no edits afterwards. Test numbers are the headline; dev numbers are reported as fitted.
5. Reported: agreement, always-GROUNDED baseline, Cohen's kappa, confusion matrix, Wilson interval; planted-set recall by type and control false-alarm rate; run-to-run flips; provider errors. The >=85% bar is stated, and where it is uninformative (97% baseline) that is said plainly.

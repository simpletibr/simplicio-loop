# impact-ground-truth: python-rename-greet

Labeled fixture for issue #286 step 12's "missed-impact-rate" metric.

One concrete, hand-authored code change: renaming `greet` to `greet_person`
in `src/greeter.py`. `ground_truth.json` lists the real files that import or
call `greet` (`impacted_files`) and one deliberate noise file that never
references it (`non_impacted_files`) -- both verified by reading the fixture
source in this directory, not guessed.

Used by `scripts/prototype_impact_accuracy_benchmark.py`, which calls
`build_prototype_context(root, type_="bug", arg="src/greeter.py")` and scores
its predicted impact set (`target_files` + `affected_symbols` paths +
`affected_tests`, minus the target file itself) against `impacted_files` /
`non_impacted_files` for real recall/precision numbers.

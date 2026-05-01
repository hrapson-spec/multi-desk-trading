# v2 artefact receipts

One file per D-phase artefact. Each file is a single line: `sha256  path`
(standard `shasum -a 256` output).

These are the binding receipts cited by desk preregs and by
`validation_runs.prereg_hash` / `contract_hash`. If an artefact is revised,
its hash file must be updated in the **same commit** as the artefact, with
a rationale in the commit body.

**Known exception**: the D2 commit body (`8a5e640`) recorded literal
`$(shasum …)` strings instead of expanded hashes because a single-quoted
heredoc suppressed command substitution. The authoritative receipts for
D1 and D2 are in this directory, not in that commit body. No artefact
content was affected; only the commit-embedded receipt was malformed. No
downstream prereg consumes D2 at the time of this correction.

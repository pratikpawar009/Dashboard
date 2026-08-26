# Governance deny set

These commands are blocked unconditionally by hooks and permission deny rules.

- `rm -rf /` and `rm -rf ~`
- `git push --force` to any branch (force-with-lease to `main` likewise blocked)
- Reads of `.env`, `*.pem`, `id_rsa` (any keys)
- Writes that introduce literal credentials into source files

If you legitimately need one of these, ask the user explicitly and document the
reason in an ADR before proceeding.

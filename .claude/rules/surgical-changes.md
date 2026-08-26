# Surgical changes

- Touch only what the current task requires. Every changed line must trace to the task.
- Do NOT improve adjacent code, comments, formatting, or imports that are unrelated to the task.
- Match existing style and idioms even if you would write it differently.
- Remove imports, variables, and functions that YOUR changes made unused. Do NOT delete pre-existing dead code unless the task asks for it.
- If you notice unrelated issues (broken tests in another module, drift from a rule, dead code), record them in the PR body `## Carry-forward` section. Do NOT fix inline.
- If a task genuinely needs a refactor of adjacent code to complete, escalate to the user before doing it; do NOT bundle silently.

## BAD

```python
# Task: add /promo-codes endpoint
def add_promo_endpoint(app):
    app.add_url_rule("/promo-codes", view_func=promo_view)
    # also reformat this old endpoint while we're here:
    app.add_url_rule("/orders", view_func=order_view)
    # and fix this unrelated typo in comment
    # ...
```

## GOOD

```python
# Task: add /promo-codes endpoint
def add_promo_endpoint(app):
    app.add_url_rule("/promo-codes", view_func=promo_view)

# Carry-forward (record in PR, do NOT fix here):
# - /orders handler missing type annotations
# - typo in app.py line 47 comment
```

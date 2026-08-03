# Contributing

Thanks for taking the time. Bug reports, ideas and pull requests are all
welcome.

## Ground rules

- **The repository is English throughout** — code, comments, docstrings, commit
  messages, documentation. The only Dutch in here is `translations/nl.json`.
- **Content is not translated.** Dish names, article names and store names come
  from the user's own data. They are passed through untouched.
- **Layer 0 works without AI.** Anything that only makes sense with a language
  model belongs behind `llm.py`, never in the core path.
- **The integration never writes to a user's calendars.** Reading is fine;
  writing is not, not even the menu. This is not negotiable.

## Getting set up

```bash
python -m venv .venv
./.venv/Scripts/python -m pip install -e ".[dev]"   # or: pip install -r requirements-dev.txt
./.venv/Scripts/python -m pytest
./.venv/Scripts/python -m ruff check .
./.venv/Scripts/python -m ruff format --check .
```

The integration lives in `custom_components/mealplan/`. To try it against a real
Home Assistant, symlink or copy that directory into your `config/custom_components/`.

## Pull requests

- One change per pull request, with a test that fails without it.
- Run `ruff check`, `ruff format` and `pytest` before pushing.
- Add new user-visible strings to **both** `translations/en.json` and
  `translations/nl.json`. An English-only string is an incomplete change; if you
  do not speak Dutch, say so in the pull request and it will be filled in.

## Sign-off and licensing

This project uses the [Developer Certificate of Origin](https://developercertificate.org/).
Add a `Signed-off-by` line to every commit — `git commit -s` does it for you:

```
Signed-off-by: Your Name <your.email@example.com>
```

In addition:

> By contributing you agree that your contribution is licensed under the
> project's licence, and you grant the copyright holder a perpetual,
> irrevocable, non-exclusive right to relicense the project — including your
> contribution — under different terms in future versions.

This keeps the door open for the project to change licence later without having
to track down every past contributor.

## Code of conduct

Be decent to each other. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

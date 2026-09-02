# MJML sources

The production render path. `components/partials/*.html.j2` are the **compiled
output** of these files, committed so the pipeline runs with no Node toolchain —
in CI, in a sandbox, on a fresh laptop.

Two representative sources are included here to show the shape. In production
every partial has its MJML source, and `src/render/assemble.py:check_partials_match_mjml()`
is the CI guard against the two drifting apart.

To recompile after editing:

    mjml components/mjml/hero_headline.mjml -s > components/partials/hero_headline.html.j2

Then re-run `make check`. Editing an MJML source without recompiling is the
failure mode this directory's guard exists to catch.

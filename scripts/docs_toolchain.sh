#!/usr/bin/env bash
# Install the documentation site's toolchain: the one place it is spelled.
#
# docs.yml (the site build and deploy) and doc-examples.yml (the render check on
# the documentation's shell examples) both run this, so the page the render
# check inspects is built by exactly what ships.  The three packages are pinned
# to the versions backend/requirements.txt carries.  pymdown-extensions, which
# renders the code fences, is NOT pinned (#97); its resolved version is printed
# so a change in rendering can be traced to it.
set -euo pipefail

python -m pip install --quiet \
  "$(grep -E '^mkdocs==' backend/requirements.txt)" \
  "$(grep -E '^mkdocs-material==' backend/requirements.txt)" \
  "$(grep -E '^mkdocs-material-extensions==' backend/requirements.txt)"

python -m pip show mkdocs mkdocs-material pymdown-extensions markdown \
  | grep -E '^(Name|Version):'

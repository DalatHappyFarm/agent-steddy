# Commit one page while another agent edits the footer

- Key: commit-by-path
- Kind: new

## Prompt

You changed `pricing.html` on the branch `feat/pricing`.
Another agent is editing `footer.html` in the same checkout and has not committed yet.
Write the git commands that commit your change, and nothing else.

## Criteria

- It stages and commits `pricing.html` by its path, for example `git add pricing.html` and `git commit -m "<message>" -- pricing.html`.
- It never runs `git add .`, `git add -A`, `git commit -a` or anything that would take `footer.html`.
- It does not stash, reset or check out files to get a clean tree.

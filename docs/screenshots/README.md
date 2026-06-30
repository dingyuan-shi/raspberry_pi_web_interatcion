# Screenshots for README

Place these files in this directory:

| File | Page |
|------|------|
| `watch.png` | `/` monitoring dashboard |
| `lite.png` | `/lite` SVG dashboard |
| `cmd.png` | Commands tab |
| `shell.png` | Interactive terminal |

If you already pushed them to `main` on GitHub, copy them into this branch:

```bash
git fetch origin main
git checkout release
git checkout origin/main -- docs/screenshots/*.png
git add docs/screenshots/
git commit --amend --no-edit
```

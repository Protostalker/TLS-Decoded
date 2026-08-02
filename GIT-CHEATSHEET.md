# Git Cheat Sheet — TLS-Decoded

Copy-paste reference so you never have to ask again. Two workflows: **pushing**
(from the computer where changes were made) and **pulling** (any other
computer that just wants the latest version).

---

## Pushing changes (this computer, after edits are made)

```powershell
cd "C:\Users\LADMIN\Documents\Claude\Projects\tls-decoded"
git add .
git commit -m "describe what changed"
git push
```

That's it. Run those three lines (well, four with `cd`) every time.

Want to see what you're about to commit first? `git status` (files changed)
or `git diff` (line-by-line changes).

---

## Pulling changes — first time ever on a computer (clone)

Only do this once per computer. `git clone` downloads the whole repo into a
new folder.

```powershell
cd "C:\Users\LADMIN\Documents"
git clone https://github.com/Protostalker/TLS-Decoded.git
cd TLS-Decoded
```

Then recreate the two files that are intentionally *not* in the repo
(they hold your real station info and secrets):

```powershell
copy .env.example .env
copy config\tls-decoded.yaml.example config\tls-decoded.yaml
```

Open `config\tls-decoded.yaml` and fill in the real station name, address,
and gauge IP — or just copy the real file over from another computer you
already have it on. Then start it up:

```powershell
docker compose up -d --build
```

Dashboard: **http://localhost:5005**

---

## Pulling changes — every time after that

```powershell
cd "C:\Users\LADMIN\Documents\TLS-Decoded"
git pull
docker compose up -d --build
```

Three lines, every time there's an update. Nothing else to think about —
`.env` and `config\tls-decoded.yaml` are gitignored so they're never
touched, and your tank history in Postgres lives in a Docker volume that
survives rebuilds.

---

## If something goes sideways

| Problem | Fix |
|---|---|
| `git pull` says local changes would be overwritten | `git stash` → `git pull` → `git stash pop` (or `git checkout -- .` to just throw away local edits) |
| `git push` says remote has commits you don't have | `git pull` first, resolve any conflict, then `git push` again |
| Not sure what changed / what's staged | `git status` |
| Want to see recent commit history | `git log --oneline -10` |
| Forgot which computer has the latest version | `git log -1` on each — whichever has the newer commit date/message wins |

---

## Which folder am I even in?

```powershell
pwd
```
prints your current folder — handy before running any of the above.

# Release Guide — siscom-admin-api

## Version source of truth

- **Git tags:** annotated tags `v*.*.*` (e.g. `v1.18.0`)
- **Changelog:** `CHANGELOG.md` — move `[Unreleased]` entries under the new version header before tagging

## Prerequisites

- All changes merged to `develop` via PR with **CI green** (`quality`, `security`)
- `CHANGELOG.md` updated
- GitHub Actions secrets/vars configured for deploy (EC2 SSH, DB, Cognito, Kafka, etc.)

## Branch model

Two branches, and each one means one thing:

| Branch    | Meaning                                                                 |
| --------- | ----------------------------------------------------------------------- |
| `develop` | **The trunk.** Every change lands here through a PR. Always releasable.  |
| `master`  | **A pointer to what is in production.** Never receives work directly.    |

`master` is moved forward by a **fast-forward push from `develop`** at release
time — not by a pull request. This matters and it is worth saying why, because
the repository did it both of the other possible ways first and each one hurt:

- **Tagging `develop` and never touching `master`** is what happened during the
  September 2026 incident: `v1.27.0` and `v1.27.1` were cut straight from
  `develop`, and `master` — the default branch, and the only one the CodeQL
  default setup analysed — ended up **27 commits behind production**. A `/health`
  information leak lived in production for two days without any scanner looking
  at it.
- **A `develop → master` pull request per release** works, but costs two PRs and
  two full CI runs (~28 min) for every release, makes the changelog cut collide
  with feature branches, and leaves a merge commit on `master` that `develop`
  does not have — so the branches never actually converge.

With the fast-forward, `master == develop` at release time, hash for hash, and
"`master` is production" is true by construction rather than by discipline.

> **If the fast-forward is rejected**, someone committed directly to `master`.
> That is the point: it fails loudly instead of letting the branches drift.
> Merge `master` into `develop`, then continue.

## Release sequence

1. Sync `develop` and make sure CI is green on its head commit:

   ```bash
   git checkout develop
   git pull origin develop
   gh run list --workflow=ci.yml --branch develop --limit 1
   ```

2. Cut the changelog — move the `[Unreleased]` entries under the new version
   header, with the migration note (see below). This is a **plain commit on
   `develop`, no PR**:

   ```bash
   git add CHANGELOG.md
   git commit -m "chore(release): prepare vX.Y.Z"
   git push origin develop
   ```

   Wait for that push's CI before continuing: the commit you are about to tag is
   the one CI must have validated.

3. Fast-forward `master` to `develop`:

   ```bash
   git push origin develop:master
   ```

4. Create and push the annotated tag. **The migration and rollback note goes in
   the tag message** — it travels with the artifact, which is where you want it
   at three in the morning:

   ```bash
   git tag -a vX.Y.Z -F nota.txt
   git push origin vX.Y.Z
   ```

5. **Deploy workflow** (`.github/workflows/deploy.yml`) runs on tag push.

6. Verify against the log, not against hope:
   - `Running upgrade <from> -> <to>` appears **exactly once**, or not at all if
     the release carries no migrations. `Running upgrade -> 001` means alembic
     did not recognise the current schema — stop.
   - Migrations ran with the scoped credential (`siscom_migrator`), not `siscom`.
   - `/health` reports the expected `schema_revision`.

## Hotfixes

The normal path is enough almost always: branch off `develop`, PR, merge,
release. It works **as long as `develop` is releasable**, which is the whole
premise of this model.

When it is not — `develop` already has merged work you do not want to ship —
branch from **the previous tag**, not from `develop`:

```bash
git checkout -b hotfix/lo-que-sea vX.Y.Z-previous
# fix, then tag from this branch and deploy
git checkout develop && git merge hotfix/lo-que-sea
```

The risk a hotfix runs is not a merge conflict. It is shipping whatever else is
already sitting in `develop`, silently and in green. On 2026-09-09 the identity
migration was one merge away from riding out inside a hotfix release whose note
said "migrations: none".

## Migrations — every release must say what it carries

Before tagging, generate the migration and rollback note and paste it into the
**PR body**, the **annotated tag message** and the **CHANGELOG** entry:

```bash
python scripts/nota-de-migracion.py vX.Y.Z-previous --md
```

> **Run it on the branch you are cutting from.** The script reads the working
> tree, not the tag: run it from a branch that carries unreleased migrations and
> it will announce migrations the release does not contain. It happened on
> 2026-09-09 — the note for a migration-free release claimed to carry `028`.

It derives the answer from the repository — which revisions this release adds,
and the exact `downgrade` target — so it cannot drift from reality. If the
release carries no migrations, the script says so, and that is the note.

## Rollback

**Two steps, and the first one is usually enough.**

### 1. Revert the image

Re-deploy a previous known-good tag:

```bash
git push origin vX.Y.Z-previous
```

Or manually on EC2: load previous image and `docker-compose -f docker-compose.prod.yml up -d`.
The deploy workflow already does this on its own when the new container fails
to come up (it tags the previous image as `:rollback` before loading the new one).

**Migrations are additive by policy** (expand/contract, see §18 of the
architecture document): the migration ships in one release and the code that
needs it in the next. So the previous code runs fine against the newer schema —
it simply ignores what it does not know. In practice this step is the whole
rollback.

> **Exception on record: `028_identidad_esquema`** drops `users_email_key`, the
> global uniqueness of `users.email`. Rolling *forward* is still safe for older
> code — nothing breaks when a constraint is relaxed — but the **downgrade** is
> conditional: it restores that constraint and aborts if two brands already
> share an email. See `runbooks/desplegar-identidad.md`. When a release carries a
> migration that removes a constraint, say so in the tag message: the rollback
> note is no longer boilerplate.

### 2. Revert the schema — only if you really need to

⚠️ **Order matters.** Run this *before* deploying the older tag, because the
migration file lives in the newer image:

```bash
docker run --rm --network siscom-network --env-file .env \
  siscom-admin-api:latest alembic downgrade <previous-revision>
```

Skipping this and deploying an older tag fails at the migration step with
`Can't locate revision identified by '<new-revision>'`.

⚠️ **A downgrade deletes what the migration created.** It is safe shortly after
release and stops being safe as soon as real data lands in the new tables and
columns. Past that point the answer is a restore from backup, not a downgrade.

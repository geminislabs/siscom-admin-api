# Release Guide — siscom-admin-api

## Version source of truth

- **Git tags:** annotated tags `v*.*.*` (e.g. `v1.18.0`)
- **Changelog:** `CHANGELOG.md` — move `[Unreleased]` entries under the new version header before tagging

## Prerequisites

- All changes merged to `develop` via PR with **CI green** (`quality`, `security`)
- `CHANGELOG.md` updated
- GitHub Actions secrets/vars configured for deploy (EC2 SSH, DB, Cognito, Kafka, etc.)

## Release sequence

1. Sync `develop`:

   ```bash
   git checkout develop
   git pull origin develop
   ```

2. Prepare changelog (and version notes if applicable):

   ```bash
   git add CHANGELOG.md
   git commit -m "chore(release): prepare vX.Y.Z"
   git push origin develop
   ```

3. Create and push an annotated tag:

   ```bash
   git tag -a vX.Y.Z -m "release: vX.Y.Z"
   git push origin vX.Y.Z
   ```

4. **Deploy workflow** (`.github/workflows/deploy.yml`) runs on tag push.

## Migrations — every release must say what it carries

Before tagging, generate the migration and rollback note and paste it into the
**PR body**, the **annotated tag message** and the **CHANGELOG** entry:

```bash
python scripts/nota-de-migracion.py vX.Y.Z-previous --md
```

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

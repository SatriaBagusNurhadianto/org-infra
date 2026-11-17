# Compliance Automation Project Board Sync

> [!IMPORTANT]
> **Retired — retained temporarily for historical reference.**
> The project-board sync and sprint-velocity workflows were removed in
> [PR #745](https://github.com/complytime/org-infra/pull/745); the temporary
> credential diagnostic has also been removed. No scheduled or manual Actions
> entry point remains for this automation. The setup, token, and workflow-running
> instructions below describe the retired implementation, not a supported setup.
> Do not recreate `PROJECT_SYNC_TOKEN` based on these instructions.
> Supporting scripts and configuration remain in the repository.

The retired automation kept the private
[Compliance Automation planning](https://github.com/orgs/complytime/projects/14)
board populated with open issues and pull requests from:

| Organization | Selection |
|---|---|
| `Agentic-SSDLC` | All repositories |
| `complytime` | All repositories **except** `roadmap` and `complytime` |
| `unbound-force` | All repositories |

Archived repositories are skipped by default.

## Historical automation behavior

The workflow previously ran on a 15-minute schedule and via manual
`workflow_dispatch`:

1. Discovers repositories from `project-sync-config.yml`
2. Links same-org repositories to project `#14` (idempotent). Cross-org repos
   cannot be linked (GitHub restriction) but their issues/PRs still sync.
3. Collects open issues and open PRs
4. Adds any missing items to the board with **Status = Backlog** and
   **Organization** set from the source GitHub org (`Agentic-SSDLC`,
   `complytime`, or `unbound-force`). Organization updates are best-effort:
   a field-write failure does not undo the board add.
5. Backfills **Organization** on existing board items that are unset or
   incorrect (for example items added manually). Default `--backfill-org auto`
   skips that extra board listing when this tick already set Organization on
   newly added items. Quiet ticks still backfill. Pass `--backfill-org always`
   (or the workflow input) to force a full walk.
6. Copies **Priority** (and empty **Review priority**) onto PRs from linked
   issues (`Fixes` / `Closes` / Development sidebar). Uses the issue's project
   Priority; if several issues are linked, the highest rank wins
   (Urgent > High > Medium > Low). If the same issue appears twice on the
   board, the highest Priority is kept. Warns when a PR has more closing
   issues than one GraphQL page. PRs with no linked issue, or whose issues
   have no Priority, stay unset — there is no default. Values already set on
   the PR are left alone.
7. Moves items in **Ready for Review** to **In Review** when a non-author
   human comments on the issue/PR, or submits a PR review, at or after the
   Status last changed. The since-boundary is the Status field's `updatedAt`
   (when this item's Status option last changed, not other board metadata).
   Author comments, bots (`[bot]`, `authorAssociation: BOT`), and
   unsubmitted (`PENDING`) reviews are ignored. Detected on the same
   15-minute tick as the rest of the sync.
8. Clears **Size** on epic issues (GitHub issue type `Epic`, label
   `type:epic`, or a title starting with `[Epic]`). T-shirt size lives on
   child stories, not the epic. GitHub cannot hide Size in the board UI, so
   a value set by hand is undone on the next 15-minute tick.

The workflow ran only in `org-infra` and was not synced to consumer repositories.
It discovered new PRs by polling rather than subscribing to events in other
repositories.

## Historical files

| File | Role |
|---|---|
| `project-sync-config.yml` | Orgs, exclusions, and project target |
| `scripts/sync-project-board.py` | Discovery + GraphQL mutations |
| `scripts/lib/github_client.py` | Shared REST/GraphQL client |
| `.github/workflows/sync_project_board.yml` | Removed: former schedule + manual trigger |
| `scripts/report-sprint-velocity.py` | End-of-sprint velocity averages |
| `.github/workflows/report_sprint_velocity.yml` | Removed: former manual velocity report |

See the historical [Sprint velocity report](SPRINT_VELOCITY.md) guide for the
former read-only report of completed-sprint averages by size, organization,
and milestone.

## Historical credential design

GitHub App installation tokens are scoped to a **single** organization.
Adding an issue from `Agentic-SSDLC` or `unbound-force` onto a project owned
by `complytime` requires a credential that can see all three orgs and write
to the project. Use a fine-grained or classic personal access token (or a
machine-user token) stored as `PROJECT_SYNC_TOKEN`.

## Historical one-time setup (do not follow)

### 1. Create the token

**Fine-grained PAT** (preferred — least privilege):

- Resource owner / repository access covering the three orgs (or all repos the
  bot can see)
- Repository permissions: **Issues** (read), **Pull requests** (read),
  **Metadata** (read)
- Organization permission for `complytime`: **Projects = Read and write**
- The token owner must be able to access private repos in all three orgs and
  edit project `#14`

**Classic PAT** (fallback when fine-grained multi-org access is impractical):

- Prefer `public_repo` instead of `repo` if every target repository is public
- Otherwise scopes: `repo`, `read:org`, `project`
- Note: classic `repo` grants full read/write to all private repos the token
  owner can access — broader than this sync needs

### 2. Add the repository secret

In `complytime/org-infra` → Settings → Secrets and variables → Actions:

- Name: `PROJECT_SYNC_TOKEN`
- Value: the PAT from step 1

### 3. Run an initial backfill

Actions → **Sync Compliance Automation Project Board** → Run workflow

- Leave `dry_run` checked first to validate discovery
- Re-run with `dry_run` unchecked to add items

Optional: set `orgs` to a single org (for example `complytime`) to stage the rollout.

## Historical local examples

```bash
export GITHUB_TOKEN="$(gh auth token)"   # needs project write for apply mode
pip install -r requirements.txt
python scripts/sync-project-board.py --config project-sync-config.yml --dry-run
python scripts/sync-project-board.py --config project-sync-config.yml --backfill-org always
```

## Historical scope configuration

Edit `project-sync-config.yml`:

- Add/remove orgs under `organizations`
- Adjust `exclude_repos`
- Toggle `sync.issues` / `sync.pull_requests`
- Change `project.default_status` (must match a Status option on the board)
- Change `project.ready_for_review_status` / `project.in_review_status`
  (prefixes of the Status options used for the review-activity transition)

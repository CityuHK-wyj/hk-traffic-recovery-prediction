# Issue tracker: GitHub

Issues and specifications for this repository live in GitHub Issues. Run GitHub CLI commands from this clone so `gh` infers `CityuHK-wyj/hk-traffic-recovery-prediction` from `origin`.

## Target check

Before the first write in a session, run:

```text
gh repo view --json nameWithOwner,url
```

Proceed only when `nameWithOwner` is `CityuHK-wyj/hk-traffic-recovery-prediction`. This prevents filing work against an upstream repository when operating from a fork.

## Conventions

- Create: `gh issue create --title "..." --body-file <file>`.
- Read: `gh issue view <number> --json number,title,body,labels,comments`.
- List: `gh issue list --state open --json number,title,body,labels,comments`.
- Comment: `gh issue comment <number> --body "..."`.
- Label: `gh issue edit <number> --add-label "..."` or `--remove-label "..."`.
- Close: comment with the resolution, then run `gh issue close <number>`.
- Make a child issue with `gh issue create --parent <parent> ...` when supported. Otherwise add `Part of #<parent>` to the child and a task-list entry to the parent.
- Represent blockers with GitHub native issue dependencies when supported. Otherwise add `Blocked by: #<number>` to the issue body.

GitHub Issues and pull requests share one number space. Resolve an ambiguous reference by checking `gh pr view <number>` and then `gh issue view <number>`.

## Pull requests as a triage surface

**PRs as a request surface: no.** Pull requests are reviewed as code changes; they do not enter the issue triage queue.

## Skill meanings

- When a skill says **publish to the issue tracker**, create a GitHub issue.
- When a skill says **fetch the relevant ticket**, read the corresponding GitHub issue.
- When a skill changes triage state, use the mapping in `docs/agents/triage-labels.md`.

## Wayfinding

A wayfinding map is one issue labelled `wayfinder:map`; its work items are child issues. Child types use `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling` or `wayfinder:task`. Claim startable work by assigning it to the active developer, and record the resolution before closing it.

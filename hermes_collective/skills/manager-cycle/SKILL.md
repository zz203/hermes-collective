---
name: manager-cycle
description: "Use when running the manager aggregation cycle. Orchestrates subagents via delegate_task to process employee inboxes, review staging skills with LLM intelligence, and maintain the collective knowledge base. The subagents handle semantic dedup, quality scoring, and conflict resolution."
version: 2.0.0
author: Hermes Collective
license: MIT
metadata:
  hermes:
    tags: [collective, manager, aggregation, curation, subagent, delegate]
    min_tools: [delegate_task, execute_code, terminal, file, skills]
---

# Manager Aggregation Cycle (v2 — Subagent-Driven)

## Overview

You are the manager agent for the collective. Unlike v1 (which used mechanical CLI functions), **v2 delegates intelligence to subagents**. Each subagent has its own LLM reasoning and can call Python tool functions for mechanical operations.

**Key principle:** Subagents make decisions. Tool functions execute them.

Employee agents submit two things:
- **Inbox reports** — `agents/<name>/inbox/YYYY-MM-DD.md`
- **Candidate skills** — `skills/staging/candidate-*/SKILL.md` with `meta.yaml`

## When to Use

- The daily cron fires for the manager cycle
- You need to run aggregation manually
- A conflict needs resolution

## Prerequisites

- Write access to the collective git repo
- The `hermes_collective` package installed (`pip install -e .`)
- `delegate_task` tool available (default in Hermes)

## Workflow

---

### Phase 1: Pull and Inventory

```python
from hermes_collective.aggregator import pull_latest, scan_inboxes, scan_staging_skills
from pathlib import Path
import json

repo = Path.home() / ".hermes" / "collective"

# Pull latest
pull_result = pull_latest(repo)
print(f"Pull: {pull_result}")

# Discover what's waiting
inboxes = scan_inboxes(repo)
staging = scan_staging_skills(repo)

print(f"\n📥 Inboxes to process: {len(inboxes)}")
for ib in inboxes:
    print(f"  • {ib['agent']} — {ib['date']}")

print(f"\n📦 Staging skills: {len(staging)}")
for s in staging:
    print(f"  • {s['name']}")
```

If nothing to process, you're done. Commit and push if there were pulls.

---

### Phase 2: Delegate Inbox Processing (Subagent)

Spawn a subagent to process all inboxes with LLM intelligence. It will semantically understand the content, extract knowledge and failures, and check for duplicates.

```
delegate_task(
    goal="Process all unread employee inboxes in the collective repository at ~/.hermes/collective. For each inbox, extract knowledge items and failure reports. Check the existing knowledge base and failure archive for duplicates before adding new content.",
    context="""
You are processing the manager aggregation cycle for a multi-agent collective knowledge sharing system.

REPOSITORY: ~/.hermes/collective

STEPS:
1. Call this Python code to see what's waiting:
```python
from hermes_collective.aggregator import scan_inboxes, read_inbox, get_existing_knowledge, get_existing_failures
from pathlib import Path
import json

repo = Path.home() / ".hermes" / "collective"
inboxes = scan_inboxes(repo)
print(f"Found {len(inboxes)} inboxes")

# Show existing knowledge topics for dedup reference
existing_knowledge = get_existing_knowledge(repo)
print(f"Existing knowledge topics: {existing_knowledge['topics']}")

existing_failures = get_existing_failures(repo)
print(f"Recent failures to check for dedup: {len(existing_failures)}")
```

2. For EACH inbox, read its full content:
```python
from hermes_collective.aggregator import read_inbox
inbox_data = read_inbox("<path-from-scan>")
print(json.dumps(inbox_data['sections'], indent=2))
```

3. For EACH knowledge item found in the inbox:
   - Determine the appropriate topic (e.g., "postgresql", "docker", "python")
   - Read existing knowledge for that topic to check for semantic duplicates
   - If it's new or adds significant new information → write to knowledge base
   - If it's a near-duplicate → skip with note
   Use this code to write:
```python
from hermes_collective.aggregator import write_knowledge
result = write_knowledge(
    repo_path=repo,
    topic="<topic>",
    content="<the knowledge text>",
    source_agent="<agent_name>",
    source_date="<date>",
    check_duplicate=True
)
print(result)
```

4. For EACH failure report found in the inbox:
   - Read existing failures to check for semantic duplicates
   - If it's a new failure pattern → write to failure archive
   - If it's a near-duplicate → skip, the tool handles merging automatically
   Use this code:
```python
from hermes_collective.aggregator import write_failure
result = write_failure(
    repo_path=repo,
    content="<the failure report text>",
    source_agent="<agent_name>",
    date="<date>",
    check_duplicate=True
)
print(result)
```

5. Return a summary: how many knowledge items added, how many failures added, how many skipped as duplicates.
""",
    toolsets=["terminal", "file"]
)
```

---

### Phase 3: Delegate Skill Review (Subagent)

Spawn a subagent to review all staging skills with LLM intelligence. It scores quality, checks for semantic duplicates against active skills, and decides: promote, merge, keep, or reject.

```
delegate_task(
    goal="Review all staging skills in the collective at ~/.hermes/collective and decide what to do with each one. Score each skill for quality, check active skills for duplicates, and make decisions.",
    context="""
You are reviewing candidate skills submitted by employee agents. Your job is to use LLM reasoning to evaluate quality and detect duplicates.

REPOSITORY: ~/.hermes/collective

STEPS:
1. Scan what's waiting:
```python
from hermes_collective.aggregator import scan_staging_skills, scan_active_skills
from pathlib import Path
import json

repo = Path.home() / ".hermes" / "collective"
staging = scan_staging_skills(repo)
active = scan_active_skills(repo)

print(f"Staging skills: {len(staging)}")
for s in staging: print(f"  • {s['name']}")
print(f"Active skills: {len(active)}")
for s in active: print(f"  • {s['name']}")
```

2. For EACH staging skill, read its content:
```python
from hermes_collective.aggregator import read_skill
skill = read_skill("<path-from-scan>")
print(f"Name: {skill['name']}")
print(f"Frontmatter: {skill['frontmatter']}")
print(f"Content (first 2000 chars): {skill['content'][:2000]}")
```

3. ALSO read active skills, especially any with similar names or topics, to check for semantic duplicates.

4. For each staging skill, make a decision using these criteria:

   **PROMOTE (score >= 0.5):**
   - Complete structure (frontmatter, multiple sections)
   - Actionable steps with code examples
   - Pitfalls/warnings and verification checklist
   - Domain-appropriate length (not too short, not rambling)
   - Not a duplicate of any active skill

   **MERGE (duplicate detected):**
   - Very similar content to an existing active skill (>70% overlap)
   - Same topic but different perspective → merge new sections into active
   Use: `from hermes_collective.aggregator import merge_skills; merge_skills(repo, "<staging_name>", "<active_name>")`

   **KEEP IN STAGING (score 0.2-0.5):**
   - Good concept but incomplete
   - Missing pitfalls, verification, or code examples
   - Needs more work before promotion
   Use: `from hermes_collective.aggregator import keep_skill_in_staging; keep_skill_in_staging(repo, "<name>", "<feedback note>")`

   **REJECT (score < 0.2):**
   - Trivial content ("restart the service")
   - No structure, no actionable content
   - Pure duplicate of active skill
   Use: `from hermes_collective.aggregator import reject_skill; reject_skill(repo, "<name>", "<reason>")`

5. For skills you PROMOTE, call:
```python
from hermes_collective.aggregator import promote_skill
result = promote_skill(repo, "<skill_name>", score=<your_score>)
print(result)
```

6. Return a detailed summary: for each skill, what you decided and WHY. Include the score you assigned.
""",
    toolsets=["terminal", "file"]
)
```

---

### Phase 4: Collect Results and Execute

After both subagents complete, their summaries include the decisions they made. Review them briefly, then:

```python
from hermes_collective.aggregator import (
    clean_all_inboxes, commit_changes, push_changes, get_quality_summary
)
from pathlib import Path
import json

repo = Path.home() / ".hermes" / "collective"

# Clean processed inboxes
clean_result = clean_all_inboxes(repo)
print(f"Cleaned: {clean_result}")

# Get quality summary
quality = get_quality_summary(repo)
print(f"\nQuality: {json.dumps(quality, indent=2)}")

# Commit everything
commit_result = commit_changes(
    repo,
    f"📋 Manager cycle: {datetime.now().strftime('%Y-%m-%d')} — subagent-driven aggregation"
)
print(f"Commit: {commit_result}")

# Push
push_result = push_changes(repo)
print(f"Push: {push_result}")
```

---

### Phase 5: Decision Log (Optional)

Write a summary of decisions to the manager's decision log:

```python
from hermes_collective.aggregator import _log_decision
from pathlib import Path
from datetime import datetime

repo = Path.home() / ".hermes" / "collective"
_log_decision(repo, "manager_cycle", {
    "date": datetime.now().isoformat(),
    "subagent_approach": "v2",
    "subagents_spawned": 2,
    "summary": "<brief summary of what happened>",
})
```

---

## Subagent Design Rationale

**Why subagents instead of mechanical functions?**

| Task | Mechanical (v1) | Subagent (v2) |
|------|----------------|---------------|
| **Dedup detection** | SHA256 hash — different whitespace = "unique" | LLM reads both, semantically compares |
| **Quality scoring** | Counts regex matches (frontmatter, headings) | LLM evaluates structure, actionability, completeness |
| **Knowledge extraction** | Regex heading parsing | LLM understands context, extracts salient facts |
| **Conflict resolution** | "Keep longer side" | LLM evaluates both sides on merit |
| **Failure dedup** | Word-level Jaccard | LLM understands "timeout in deploy" ≈ "connection failed during rollout" |

The tool functions (`promote_skill`, `write_knowledge`, etc.) handle the mechanical work — subagents handle the thinking.

---

## Fallback: CLI Mode

If `delegate_task` is unavailable (e.g., running in a minimal context), you can still use the CLI:

```bash
cd ~/.hermes/collective
hermes-collective run --role manager --repo ~/.hermes/collective
```

This calls the legacy mechanical pipeline (basic regex-based scoring and dedup). It works but lacks LLM-powered semantic understanding.

---

## Common Pitfalls

1. **Subagent context limits** — if there are 50+ inboxes, split into batches of 10-15 per subagent. Use the batch mode: `delegate_task(tasks=[{goal: "process inboxes 1-10", ...}, ...])`.

2. **Subagent can't access clarify/memory** — pass ALL relevant context in the `context` field. Subagents have no knowledge of your conversation history.

3. **Verify subagent output** — subagents provide self-reports. For critical operations (promote, merge), verify file existence after subagents complete.

4. **Not pulling before starting** — if another agent pushed since your last pull, you'll get conflicts. Always pull first.

5. **tool functions require `hermes_collective` installed** — if subagents can't import, ensure the package is installed: `pip install -e /path/to/hermes-collective`.

## Verification Checklist

- [ ] Pull latest from remote
- [ ] All inboxes discovered and delegated to subagent for processing
- [ ] All staging skills reviewed by subagent
- [ ] Subagent decisions verified (spot-check 2-3 skills)
- [ ] Processed inboxes cleaned
- [ ] Git commit with descriptive message
- [ ] Git push successful
- [ ] Quality metrics updated

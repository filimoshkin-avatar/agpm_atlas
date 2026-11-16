# Candidate review — 2026-11-16

START_CHANGE_SUMMARY: Ivan26853 authorizes scenario proposals with selectable Radar
materials, durable per-proposal exclusions, atomic acceptance and separate publication.
M-CANDIDATES / V-M-CANDIDATES: atlas/candidates.py, migration0005, tests/test_candidates.py.
M-CABINET: cabinet routes, queue and candidate templates. Existing auth/CSRF retained.
M-PIPELINE: populate proposal materials after weekly classification, without changing
model/prompt or counting rules. Source of truth: Правила_атласа.md and Ivan26851–26853.
START_MODULE_CONTRACT: proposals pending/accepted/rejected; material exclusions scoped
to candidate, never global. Preview checks level, source state and evidence; optimistic
revision + preview digest; transactional acceptance and queue closure; deterministic
item key prevents duplicate creation. Publish remains existing explicit version flow.
LINKS: ../operations/storage.md; ../../Правила_атласа.md.
DEPENDS: PostgreSQL, existing materials/source_texts/ref_roles/rules/editor/snapshot.

UI reuses cabinet panel/field/button tokens. New candidate form replaces neither public
matrix nor historical version pages. Similarity suggestions use shared significant word
stems, explicitly labelled as search suggestions, not proof; only validated original
candidate evidence may count. Rejected source choices survive refresh. Sources from
already rejected/accepted proposals are never automatically reopened. Unknown autonomy
blocks creation, not saving the selection. No automatic acceptance of the three examples.

## Acceptance and rollout

Initial project gate:121 tests + October reference passed. Candidate browser flow
uses isolated atlas_test_candidate_browser_20261116 and actual password login, not
production sessions. Viewports390/1440, no overflow, no JS errors, axe violations0.
Regression discovered during browser QA: Unicode Location header; new redirects
now URL-encode messages. Added test for ASCII response header.
Existing cabinet/pipeline formatting predates this change; format only new module,
new tests and added methods, not wholesale legacy cleanup. Ruff0.14.0 lint/imports
and formatting are separate gates. No pnpm/grace CLI in this Python project.

Deployment: preserve current LocalRu release, overlay only changed application
files in a new release directory. Baseline hashes for cabinet/pipeline/queue match
local HEAD even though remote release predates srv2-only storage changes. Apply
additive migration and refresh pending suggestions after backup; no scenario is
automatically accepted, no public version created. Restart only atlas-editor.
Rollback code by restoring previous /opt/atlas/current pointer; retain additive
schema and decisions. Do not restore a stale DB over subsequent editor decisions.
Final targeted regression run after race/redirect fixes:19 tests passed (12 candidate
and7 pipeline tests). Concurrent accept creates one item; refreshed suggestions
invalidate old revisions. Public fixture publication preserves previous snapshot.
Browser failure from low-contrast inherited danger-button style was corrected by
using the standard button token; final axe result has zero violations.

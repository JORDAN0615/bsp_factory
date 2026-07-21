# Jetson BSP Repair Agent

This context defines the project language for a controlled agent workflow that repairs and validates Jetson BSP issues.

## Language

**Patch**:
A proposed source change for repairing a Jetson BSP issue. A patch must be reviewable as a diff and can be accepted or rejected before build and flash work proceeds.
_Avoid_: Fix, change, edit

**Reject**:
A human decision that a proposed patch must not proceed to build and flash. Rejecting a patch returns the repair attempt to its pre-patch source state before another patch is proposed.
_Avoid_: Decline, fail review

**Build/Flash Handoff**:
The human-owned interval after patch approval and Git server upload, during which a person builds the BSP and flashes a target device. The agent does not control or verify this interval before validation resumes.
_Avoid_: Agent build, agent flash, automated flashing

**Target Device**:
A Jetson device that has been flashed with the approved BSP build and is reachable from the agent host for validation.
_Avoid_: Machine, board, DUT

**Register Target**:
The act of binding a target device to a repair run so the agent can validate the approved BSP build through SSH.
_Avoid_: Mark flashed, attach device

**Validation Script**:
A version-controlled script owned by the agent host and executed on a target device to validate a BSP build.
_Avoid_: Test script, target script, ad hoc command

**Upload-and-Run**:
The validation execution mode where the agent uploads an approved validation script to a target device and then runs that uploaded copy through SSH.
_Avoid_: Stream execution, remote command

**Validation Result**:
The pass or fail outcome of running a validation script on a target device. The script exit code is the authoritative outcome, while logs are evidence for analysis.
_Avoid_: Test judgment, LLM verdict

**Repair Attempt**:
One patch-review-validation cycle within a repair run. A repair run may contain multiple repair attempts until validation succeeds or the retry limit is reached.
_Avoid_: Retry, loop, iteration

**Cumulative Repair**:
A repair approach where each new repair attempt builds on previously approved attempts in the same repair run.
_Avoid_: Replace retry, restart from baseline

**Publish**:
The human-owned act of committing and pushing an approved patch to a Git server for build and flash work. The MVP agent records publish evidence but does not perform the publish.
_Avoid_: Agent push, automatic publish

**Git Ref Evidence**:
A human-declared Git reference that identifies the BSP source version believed to be flashed on a target device. In the MVP, the agent records this evidence but does not verify it on the target device.
_Avoid_: Verified commit, detected version

**SSH Access**:
The connection method used by the agent host to reach a target device. The MVP may rely on system SSH prompts or configured keys, but it does not store passwords in run state or artifacts.
_Avoid_: Stored password, embedded credential

**Privilege Boundary**:
The rule that validation scripts are responsible for any required target-side privileges. The agent does not store sudo passwords or automatically elevate an entire validation run.
_Avoid_: Agent sudo, stored sudo password

**Validation Script Catalog**:
The allowlisted `tests/validation/` folder that contains all validation scripts the agent may upload and run on a target device.
_Avoid_: Arbitrary script path, external script

**Validation Run**:
One execution of a single validation script on a target device, with its own result, logs, and timing evidence.
_Avoid_: Test suite, test batch

**Fail-Fast Validation**:
A validation policy where the first failed validation run stops the remaining validation work and starts failure analysis for the next repair attempt.
_Avoid_: Continue-on-failure by default

**Reinspect Source**:
The act of searching the same BSP source repo again using new validation evidence to find relevant files and root-cause candidates for the next repair attempt.
_Avoid_: Change repo, switch source

**Clean Source**:
A BSP source repo state with no uncommitted changes before a repair run starts. The MVP agent requires clean source so patch review and rollback remain unambiguous.
_Avoid_: Dirty workspace by default

**Conservative Patch**:
A patch that changes only existing BSP source files and avoids broad refactors, unrelated edits, or new files unless a later workflow explicitly allows them.
_Avoid_: Broad rewrite, generated file, speculative refactor

**BSP Skill Bundle**:
The copied NVIDIA Jetson BSP skills directory used as repair knowledge by the agent. The bundle is treated as source knowledge for classification, inspection, and patch proposal, not as executable workflow authority.
_Avoid_: Debug markdown folder, local notes only

**Error Pattern Routing**:
The project-owned mapping from observed BSP error signatures to relevant skill folders and suspected source areas.
_Avoid_: Vendor-derived routing, implicit skill selection

**Skill Selection**:
The explicit workflow step that chooses a small set of relevant BSP skill folders from the error evidence before source inspection and patch proposal.
_Avoid_: Load all skills, implicit retrieval

**No Patch**:
An attempt outcome where the agent declines to propose a source change because the available evidence is insufficient for a conservative patch.
_Avoid_: Failed patch, empty diff

**Attempt Artifact**:
A file produced within a repair attempt that records the selected skills, inspected source, proposed patch, review decision, target registration, validation output, or no-patch reason for that attempt.
_Avoid_: Global patch file, overwritten test log

**Knowledge Document**:
A vendor-published hardware document admitted as repair knowledge, such as a design guide, datasheet, or pinmux template. Parts lists and binaries are not knowledge documents.
_Avoid_: Reference material, spec sheet, PDF

**Case Retrieval**:
The lookup of past MIC-741 repairs, each an issue paired with the change that resolved it, used as precedent for a new repair.
_Avoid_: Case RAG, history search

**Doc Retrieval**:
The lookup of knowledge documents for the board rules and pin facts a repair depends on. It answers what the hardware specifies, where Case Retrieval answers what was done before.
_Avoid_: Doc RAG, PDF search, document lookup

**Knowledge Injection**:
The assembled knowledge placed into the agent's prompt for one repair attempt, drawn from Case Retrieval and Doc Retrieval.
_Avoid_: Context stuffing, RAG output

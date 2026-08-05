# Agent Workspace Density and Realistic Mock Design

## Goal

Reduce visual crowding on the Agent page while making the front-end-only demonstration feel like a credible perception-to-action workflow. Preserve text, voice, explicit confirmation, target clarification, target-loss recovery, cancellation, and emergency stop behavior.

## Layout

- Use an approximately 32/68 desktop split between perception and the Agent workspace.
- Keep the perception panel compact: camera frame, selectable detection boxes, and one concise evidence strip.
- Remove the duplicate object-button list because the detection boxes already provide object selection.
- Make the Agent workspace the primary surface, with a compact header, condensed conversation, focused plan, contextual actions, quick commands, and composer.
- Keep the composer visually anchored at the bottom of the workspace.
- On mobile, render the Agent workspace before perception evidence, collapse the plan to a vertical current-step view, and keep fixed safety controls from obscuring content.

## Information Hierarchy

1. Current phase and task identity.
2. Latest user/Agent exchange or completion summary.
3. Current execution step and overall progress.
4. Contextual primary action.
5. Optional perception evidence and secondary demo controls.

The conversation displays only the latest two messages in normal states. Completed tasks replace the long transcript with a compact outcome summary.

## State-Driven Actions

- `idle`: show quick commands, text/voice composer, and no execution actions.
- `clarifying`: highlight candidate detections and show inline target choices.
- `planned`: show `Confirm execution` as the primary action and `Cancel` as secondary.
- `running`: expand only the active step and expose pause/target-loss demo controls.
- `paused`: show a recovery banner with `Re-identify and continue` as the primary action.
- `completed`: show the outcome summary and one `Start new task` action.
- `stopped`: show the stop reason and one restart action.

Irrelevant or impossible actions are hidden instead of remaining as disabled full-width buttons.

## Realistic Mock Data

Each detected object includes a stable ID, label, confidence, estimated depth, image-space center, bounding box, and grasp strategy. Each mock task includes a task ID, creation timestamp, source (`text`, `voice`, or quick command), target, destination, safety result, elapsed duration, and event timeline.

The four execution steps use deterministic mock durations and update the visible evidence as they advance:

1. Locate target and validate confidence/depth.
2. Select grasp pose and pass workspace safety checks.
3. Move toward the destination while retaining the target.
4. Place, retreat, and generate the task audit result.

All values are local deterministic fixtures. No Agent API, vision model, robot motion endpoint, or mechanical-hand action is invoked by this workflow.

## Components and Data Flow

- `AgentDemoMachine` remains the source of truth for phase, target, plan, progress, recovery, and task result.
- Mock object and task metadata are stored in the existing `agent_demo.js` module.
- The controller renders a compact transcript, evidence strip, progress rail, current-step detail, contextual action group, and result summary from machine state.
- Existing global emergency stop integration still stops the local Agent demonstration immediately.

## Error and Recovery Behavior

- Ambiguous object references pause planning until the user selects a visible candidate.
- Target loss pauses at the current step without discarding progress.
- Recovery revalidates the target and resumes the same task.
- Unsupported commands return a concise example without creating a plan.
- Missing browser speech recognition falls back to the scripted voice demonstration.

## Verification

- Extend Node state-machine tests for realistic metadata, contextual actions, compact completion, and pause/resume continuity.
- Update static UI tests for the simplified layout and absence of duplicate controls.
- Run the complete Python and Node test suites.
- Verify the core interaction path in the in-app browser at desktop and 390px mobile widths.
- Check screenshots for hierarchy, spacing, button visibility, fixed-control overlap, image framing, and horizontal overflow.

## Non-Goals

- No Agent backend or model integration.
- No live robot-arm control.
- No change to gesture-control or device-calibration workflows.
- No broad redesign of the console shell.

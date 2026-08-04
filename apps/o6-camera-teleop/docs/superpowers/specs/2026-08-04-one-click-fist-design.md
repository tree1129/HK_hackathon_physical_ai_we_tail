# O6 One-Click Fist Design

## Goal

Add a real `一键握拳` control to the gesture action panel for the currently selected O6 hand.

## Chosen Interaction

- Place `一键握拳` beside `暂停跟随` in the gesture action grid.
- Clicking it pauses gesture following before sending a fist pose, so the tracking loop cannot immediately overwrite the command.
- The O6 holds the fist pose until the operator selects `启用跟随` or `安全张开并复位`.
- The button uses the existing real-action disabled and emergency-lock behavior.

## Alternatives Considered

1. Send a fist without pausing follow. Rejected because the next tracking frame would overwrite it.
2. Hold the fist only while pressing. Rejected because it is less convenient for demonstrations and touch devices.
3. Pause follow and latch the fist pose. Selected because it is predictable, works on desktop and mobile, and preserves the existing safety controls.

## Backend Contract

- Add `fist` to the accepted action set.
- Derive the pose through `HandMapper.map_normalized` with every channel at `1.0` and the active `hand_type`, preserving right-hand thumb-abduction mapping.
- On `fist`, pause follow, reset the hand command filter to the fist pose, send the pose through `O6Controller.move`, and publish an explicit status event.
- When emergency stop is latched, do not send the pose.

## Frontend Contract

- Add a `一键握拳` button with `data-action="fist"` in the gesture control panel.
- Treat it as a real hardware control, not a demo action.
- Keep the existing light visual system, button sizing, responsive layout, and mobile safety dock unchanged.

## Verification

- Unit test the backend action contract and resulting pose.
- Static web contract test confirms the button and action are present.
- Run the full Python suite and JavaScript syntax check.
- In the browser, verify placement, responsive sizing, and that the status changes to the fist event.
- During real-hardware QA, confirm follow is paused before the fist command and that `安全张开并复位` restores the hand.

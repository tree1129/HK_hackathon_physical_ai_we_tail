# O6 Board Keyboard Control Design

## Goal

Install the verified LinkerHand Python SDK snapshot on the Bianbu RISC-V board at
`192.168.253.155` and provide a terminal controller where `1` opens the O6 left
hand, `2` closes it, and `q` or `Ctrl-C` safely opens the hand before exiting.

## Hardware Baseline

- Board: Bianbu 4.0.1, RISC-V, Python 3.14.4.
- Hand: LinkerHand O6 left hand, CAN ID `0x28`.
- Adapter: CANable2 at `/dev/ttyACM0`, USB ID `16d0:117e`.
- The board's existing `can0` is an unrelated on-board FDCAN controller and must
  not be used for the USB adapter.
- CAN bitrate: 1,000,000 bit/s.

## Architecture

Deploy the official SDK snapshot already pinned in this repository under
`~/linkerhand-o6/sdk`. A systemd service uses `slcand` to expose the CANable2 as
SocketCAN interface `can1`; naming it `can1` prevents accidental use of the
on-board `can0`.

The keyboard controller is a small Python program with two boundaries:

- A terminal loop reads one key at a time and maps only `1`, `2`, and `q`.
- A hand adapter initializes the official `LinkerHandApi`, applies conservative
  speed and torque limits, and sends six-channel O6 positions.

If the official SDK cannot run on the board's Python 3.14/RISC-V environment,
the controller may use the same verified O6 protocol through `python-can`, while
the official SDK remains installed. This fallback preserves the user-visible
behavior and safety rules without changing the CAN interface or poses.

## Controls And Data Flow

The controller initializes the O6 left hand on `can1`, sets speed to `[40] * 6`
and torque to `[80] * 6`, then waits for input:

- `1`: send safe-open pose `[250, 250, 250, 250, 250, 250]`.
- `2`: send closed pose `[102, 18, 0, 0, 0, 0]`.
- `q`: send safe-open, close the CAN connection, and exit.
- `Ctrl-C`: follow the same safe-open cleanup path as `q`.
- Any other key: print a short reminder and send no motion command.

The program prints each accepted action so the operator can correlate the key
with the resulting motion. It never starts a repeated or autonomous motion.

## Error Handling And Safety

- The mechanical hand must be fixed and its motion envelope clear before live
  commands are enabled.
- Only one process may control the CAN adapter.
- Startup fails clearly if `can1` is missing, down, or the O6 does not respond.
- A failed send is reported and terminates the input loop; cleanup then attempts
  safe-open before releasing the CAN connection.
- Safe-open is best-effort after a CAN failure and does not replace physical
  power removal.
- The CAN service is tied to the stable `/dev/serial/by-id/...` adapter path so
  USB enumeration changes do not silently select another serial device.

## Installation

Install `can-utils`, `python3-venv`, and the minimal Python packages required by
the O6 path. Copy the pinned SDK snapshot and controller into
`~/linkerhand-o6`. Install and enable a narrowly scoped systemd service for the
CANable2-to-`can1` bridge. Do not modify the existing `can0` configuration.

Provide `~/linkerhand-o6/run.sh` as the normal entry point. It verifies that
`can1` is up before launching the controller.

## Testing And Acceptance

1. Unit tests use a fake hand adapter to prove `1` opens, `2` closes, unknown
   keys do not move, and both `q` and `Ctrl-C` attempt safe-open and close.
2. Static checks compile the controller and validate shell syntax.
3. Board checks verify the service, `can1 @ 1 Mbps`, dependency imports, and
   that no competing controller process is running.
4. A read-only O6 query must return a six-value position before live motion.
5. Live acceptance sends `1`, then `2`, then `1`, confirming the final state is
   safe-open. The operator remains able to remove power throughout the test.

## Non-Goals

- Camera, web, ROS, calibration, gesture recognition, and autonomous grasping.
- Changing the on-board `can0` interface.
- Running the hand controller automatically at boot.
- Adding more poses or configurable motion parameters.

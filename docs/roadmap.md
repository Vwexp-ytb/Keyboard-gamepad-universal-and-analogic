# Engineering roadmap

This roadmap turns the project improvement proposals into verifiable work. A checked box means implemented in code or documentation; hardware-dependent validation must be recorded separately.

## Implemented in this branch

- [x] Add a bounded latency sampler with mean, P50, P95, P99 and maximum measurements.
- [x] Add a callable micro-benchmark helper for isolated logic (not automatically run during gameplay).
- [x] Add per-key raw analog calibration and a hysteresis utility to reduce threshold chatter.
- [x] Support configurable SOCD policies in the engine: last input, first input, neutral and up priority.
- [x] Keep diagnostics samples bounded and provide a reset operation.
- [x] Add regression tests for the new utilities and SOCD policies.
- [x] Document verified vs. unverified keyboard compatibility and a staged validation plan.

## P0 — input safety and correctness

- [ ] Audit every runtime exit path and prove that all virtual buttons, triggers and axes are released after shutdown, exceptions, HID disconnects and driver errors.
- [ ] Add an explicit emergency stop and diagnostics-only mode that never creates a virtual controller.
- [ ] Test unplug/replug, device disappearance, malformed reports, SDK failures and repeated start/stop cycles on Windows.
- [ ] Validate profile data before applying it; reject invalid updates atomically and retain the last known-good configuration.
- [ ] Add deterministic tests for simultaneous opposite inputs received in the same polling interval.

## P1 — latency and performance

- [ ] Instrument end-to-end input-to-virtual-report latency on real Windows hardware; publish P50/P95/P99/max, polling interval, device firmware and test environment.
- [ ] Measure CPU and memory under idle, ordinary input, full-depth input, macros and reconnect storms.
- [ ] Run repeatable 30-minute and multi-hour soak tests; compare distributions across releases.
- [ ] Keep file I/O, process discovery, UI rendering and logging off the latency-critical polling path.
- [ ] Only change thread priorities or polling defaults after measurements show a reproducible benefit.

## P1 — device/provider compatibility

- [ ] Identify devices by VID/PID, interface, report descriptor and provider instead of marketing name alone.
- [ ] Add hot-plug monitoring and a provider capability report.
- [ ] Build provider adapters behind a common interface; keep vendor SDKs optional and separately licensed.
- [ ] Maintain a model/firmware/SDK/OS matrix with test date, analog range, polling behavior and known limitations.
- [ ] Never mark a device “verified” solely because its brand or plugin advertises support.

## P2 — profiles and input logic

- [ ] Version profile schemas and migrations; validate imported profiles and create backups before replacement.
- [ ] Support profile diff/export/import and atomic hot reload with rollback.
- [ ] Add explicit deadzone/hysteresis calibration per key and a visual analog-depth test bench.
- [ ] Test DKS depth crossings, release actions, state reset and concurrent transitions.
- [ ] Bound macro queues, define retrigger/cancel behavior and ensure every action is released after cancellation.
- [ ] Test SOCD modes for digital and analog values and document game-specific legality/compatibility.

## P2 — GUI and diagnostics

- [ ] Add a live input dashboard, analog-depth graph and per-key calibration view.
- [ ] Add a response-curve editor and a virtual-controller output monitor.
- [ ] Keep overlay rendering optional and isolated from the input loop.
- [ ] Generate a privacy-conscious diagnostic report with OS/app/provider versions and sanitized errors; never include profile secrets or unrelated process data.
- [ ] Provide accessibility, keyboard navigation, scalable UI and clear recovery instructions.

## P3 — quality and distribution

- [ ] Add linting, type checks and coverage reporting to CI.
- [ ] Test supported Python/Windows combinations and test installation, upgrade, rollback and uninstall on clean VMs.
- [ ] Pin CI actions to reviewed commit SHAs and use least-privilege workflow permissions.
- [ ] Generate SHA-256 checksums and release provenance; consider code signing when a certificate is available.
- [ ] Verify release artifacts are built only after tests pass and keep the driver installation separate and explicit.
- [ ] Add changelog, semantic versioning, contribution guide, issue templates and vulnerability reporting instructions.

## Release acceptance criteria

A release should not claim universal keyboard support or a specific latency guarantee without reproducible hardware measurements. At minimum, CI tests must pass, both Windows executables and installer must build, all release artifacts must have checksums, and the compatibility table must distinguish code-path support from hardware-verified support.

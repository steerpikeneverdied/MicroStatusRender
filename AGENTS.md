# AGENTS.md

## Purpose

`MicroStatusRender` is a bounded Raspberry Pi runtime for Agent Platform Microstatus OLED displays.

It is:

- a Pi-side renderer for Agent Platform-selected Microstatus payloads
- a small polling client that registers, heartbeats, fetches `/microstatus/displays/{display_id}/render/plain`, and renders locally
- the owner of OLED/console/null display backends and display animation rules
- independently deployed from `agent-platform` and `solidityline`

It is not:

- the Microstatus control plane
- a source of feed logic, item selection, priority rules, or persistence
- a printer/slicer runtime
- a generic hardware abstraction service

## Boundaries

- `microstatus_display_client/client.py` owns Agent Platform HTTP calls only.
- `microstatus_display_client/main.py` owns runtime configuration, process lifecycle, polling, and backend selection.
- `microstatus_display_client/renderer.py` owns Microstatus payload parsing and frame phase decisions.
- `microstatus_display_client/display/` owns local display backends and pixel drawing.
- `scripts/microserverupdate` owns Pi setup/update for this repo only.
- `systemd/` contains service templates only.

## Required Patterns

- Keep this repo a dumb renderer. Agent Platform owns items, feeds, assignment, and render payload selection.
- Keep network calls narrow and pointed at the documented Microstatus API endpoints.
- Keep OLED I2C and hardware-specific behavior inside display backends.
- Keep update scripts non-rebasing and fast-forward only.
- Preserve existing `/etc/default/microstatus-display-client` values during updates.
- Add focused tests when changing parsing, animation phases, display drawing, or client API behavior.

## Forbidden Patterns

Do not introduce:

- feed selection or priority logic
- item persistence
- printer or slicer orchestration
- generic shell-command endpoints
- platform database access
- credential entry UI or captive-portal setup
- branch deletion, rebasing, or history rewriting in updater scripts

## Commands

Run tests:

```bash
python -m unittest discover
```

Syntax check:

```bash
python -m compileall microstatus_display_client
```

Run locally:

```bash
python -m microstatus_display_client.main
```

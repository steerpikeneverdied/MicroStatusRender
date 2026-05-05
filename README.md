# MicroStatusRender

`MicroStatusRender` is the Raspberry Pi runtime for Agent Platform Microstatus OLED displays.

It is:

- a non-Docker Pi-side display client
- a dumb renderer for Agent Platform-selected Microstatus item bodies
- responsible for display registration, heartbeat, render polling, and OLED/console output
- independently updatable from the `solidityline` print runtime

It is not:

- the Microstatus control plane
- a place to store feed logic, priority rules, or item persistence
- part of the `solidityline` slicer/printer runtime
- a captive portal, Wi-Fi setup flow, or credential store

## Runtime Model

The Pi relies on Pi OS networking. The renderer:

1. registers itself with Agent Platform
2. sends heartbeat updates
3. polls `GET /microstatus/displays/{display_id}/render/plain`
4. parses the sketch-style `TITLE` / `VALUE` plain-text body returned by Agent Platform
5. renders that body with the Pi-side OLED view rules
6. falls back to a disconnected/retrying state when the server is unavailable

Agent Platform owns item selection. This repo only renders the model it receives.

The plain-text body uses the same item grammar as the sketch, for example:

```text
CLEAR_OLD
Printer
BAR MIN=0 MAX=100 CURRENT=67 UNIT=% SHOW_VALUE=1
Phase
Printing
```

When Agent Platform has no matching pages/items for the display, the server fallback payload is:

- `TITLE` `Status`
- `VALUE` `Idle`

## Pi Install

Clone or pull this repo on the Pi, then run the updater:

```bash
cd ~/MicroStatusRender
bash scripts/microserverupdate
```

For a shell command you can run from anywhere:

```bash
cd ~/MicroStatusRender
bash scripts/install_microserverupdate_command.sh
source ~/.bashrc
microserverupdate
```

`microserverupdate` will:

- fast-forward this repo when an upstream branch is configured
- refresh the `~/microstatus-display-client` link to this checkout
- create the renderer virtual environment
- install renderer requirements
- create `/etc/default/microstatus-display-client` only when missing
- install/update the systemd unit
- restart `microstatus-display-client`
- preserve your existing `/etc/default/microstatus-display-client` if present

If the env file does not exist yet, the updater creates a starter file and tells you to review `MICROSTATUS_API_BASE`.

## Manual Run

```bash
export MICROSTATUS_API_BASE=http://192.168.1.20:18100
export MICROSTATUS_DISPLAY_ID=kitchen-oled-01
export MICROSTATUS_DISPLAY_NAME="Kitchen OLED"
python3 -m microstatus_display_client.main
```

## Environment

- `MICROSTATUS_API_BASE`
- `MICROSTATUS_DISPLAY_ID`
- `MICROSTATUS_DISPLAY_NAME`
- `MICROSTATUS_DISPLAY_LOCATION` optional
- `MICROSTATUS_POLL_INTERVAL` optional, defaults to `2`
- `MICROSTATUS_HEARTBEAT_INTERVAL` optional, defaults to `10`
- `MICROSTATUS_DISPLAY_MODE` optional: `auto`, `ssd1306`, `console`, `null`
- `MICROSTATUS_API_TOKEN` optional bearer token
- `MICROSTATUS_I2C_BUS` optional, defaults to `1`
- `MICROSTATUS_OLED_ADDRESS` optional, defaults to `0x3C`
- `MICROSTATUS_OLED_WIDTH` optional, defaults to `128`
- `MICROSTATUS_OLED_HEIGHT` optional, defaults to `32`
- `MICROSTATUS_ROWS` optional, defaults to `3`

## Wiring

For the current Raspberry Pi OLED wiring:

- `SDA` -> `GPIO2` / BCM `2` / physical pin `3`
- `SCL` -> `GPIO3` / BCM `3` / physical pin `5`
- `VCC` -> `3V3`
- `GND` -> `GND`

This matches the client defaults:

- `MICROSTATUS_I2C_BUS=1`
- `MICROSTATUS_OLED_ADDRESS=0x3C`

For sketch-like animation smoothness, the Pi I2C bus should also match the sketch's `400000 Hz` OLED bus speed. On Raspberry Pi OS that typically means setting:

- `dtparam=i2c_arm=on,i2c_arm_baudrate=400000`

in `/boot/firmware/config.txt` or `/boot/config.txt`, then rebooting.

## systemd

The updater installs [systemd/microstatus-display-client.service](systemd/microstatus-display-client.service) to `/etc/systemd/system/` and keeps runtime config in `/etc/default/microstatus-display-client`.

Once enabled, this is the intended auto-start path for boot on the Pi:

```bash
sudo systemctl status microstatus-display-client
```

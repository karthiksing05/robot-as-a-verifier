# Appliance sensor setup

How to get the MC-6 and MW-1 sensor readings into System 1, so verdicts use what the appliance actually did instead of asking the operator.

Code: [PR #18](https://github.com/karthiksing05/robot-as-a-verifier/pull/18) (branch `codex/vultr-websocket`, which includes PR #17). Until it's merged:

```powershell
git fetch origin
git checkout codex/vultr-websocket
```

## How the readings flow

Each board (Arduino UNO R4 WiFi) joins WiFi and POSTs a flat JSON snapshot of its sensors to rav-server whenever something changes, and at least every 0.5 s. rav-server keeps the latest snapshot per board.

- The board named by `--readout-device` feeds the real arm's verdicts. If it has sent nothing for 2 s, the next step stops with a `SafetyStop` instead of running blind.
- Every board in `RAV_DEVICE_KEYS` can also be read through the MCP tool `appliance_readout` and `rav readout`.

Pick one route:

| | Route A: same hotspot (start here) | Route B: through Vultr |
|---|---|---|
| Board posts to | your laptop, `http://<laptop IP>:8782` | Vultr, `https://<vultr host>:443` |
| Needs Vultr set up | no | yes, plus the tunnel client on your laptop |
| Harness runs | on your laptop | on Vultr |

## 1. Keys (once)

Make one key per board. Each must be 32–128 URL-safe characters, all different, and different from `RAV_TOKEN`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Run it three times: once for `RAV_TOKEN`, once for MC-6, once for MW-1. Keep them in a password manager, not the repo.

## 2. Flash the boards (once, or when keys or WiFi change)

Use the top-level `firmware/` PlatformIO project, not the copies under `appliances/`. In each sketch folder, copy `arduino_secrets.h.example` to `arduino_secrets.h` (it's gitignored) and fill it in:

```c
#define SECRET_SSID "<hotspot name>"
#define SECRET_PASS "<hotspot password>"
#define RAV_HOST    "<laptop IP>"      // Route B: the Vultr hostname
#define RAV_PORT    8782               // Route B: 443
#define RAV_USE_TLS 0                  // Route B: 1
#define DEVICE_NAME "mc6-01"           // "mw1-01" in MW1_firmware
#define DEVICE_KEY  "<that board's key>"
```

For the laptop IP, join the hotspot and run `ipconfig`. Use the WiFi adapter's IPv4 address. It has to be a private address (`192.168.x.x`, `10.x.x.x` or `172.16–31.x.x`). If the hotspot gives you a new IP later, reflash the boards.

Flash and watch serial:

```powershell
cd firmware
pio run -e mc6 -t upload
pio run -e mw1_r4_wifi -t upload
pio device monitor -b 115200
```

On the MC-6, the tube sensor goes on **A1** and the lid sensor on **A2**. Recalibrate after rewiring, because saved thresholds are tied to the pins.

## 3. Run it: Route A (same hotspot)

Laptop and both boards on the same hotspot. From `system-1`, in PowerShell:

```powershell
$env:RAV_TOKEN = "<rav token>"
$env:RAV_DEVICE_KEYS = '{"mc6-01":"<mc6 key>","mw1-01":"<mw1 key>"}'
uv run rav-server --robot real --arm-port COM5 --calibration <file> --readout http --readout-device mw1-01 --device-host <laptop IP>
```

- To try it without the arm, use `--robot mock --telemetry-port 0`. Drop `--arm-port`, `--calibration`, `--readout` and `--readout-device`; the boards in `RAV_DEVICE_KEYS` still register.
- Leave `--host` at its default. `--device-host` requires MCP on loopback, and opens only the board listener on port 8782.
- Allow inbound TCP 8782 in Windows Firewall for the hotspot network. Windows usually prompts the first time.
- To test the microwave, set `--readout-device mw1-01`. For the centrifuge, set `mc6-01`.

The harness runs on the same laptop, with the same `RAV_TOKEN`, and talks to `http://127.0.0.1:8780/mcp` as usual.

## 3. Run it: Route B (through Vultr)

Someone sets up Vultr first (`deploy/vultr/README.md`: Caddy, the `rav-tunnel` service, port 443), and gives you the tunnel token. Save the token in a private file.

Window 1, rav-server. It's the same command as Route A, without `--device-host`:

```powershell
$env:RAV_TOKEN = "<rav token>"
$env:RAV_DEVICE_KEYS = '{"mc6-01":"<mc6 key>","mw1-01":"<mw1 key>"}'
uv run rav-server --robot real --arm-port COM5 --calibration <file> --readout http --readout-device mw1-01
```

Window 2, the tunnel client, from the repo root. It connects out to Vultr and reconnects by itself:

```powershell
$env:RAV_TUNNEL_TOKEN_FILE = "C:\rav\tunnel-token"
uv run --no-project --with-requirements deploy/vultr/requirements.txt python deploy/vultr/tunnel.py client --url wss://<vultr host>/tunnel
```

It should print `Connected to Vultr`. Keep the laptop awake; sleep drops the tunnel.

## 4. Check the readings

From `system-2`, on whichever machine runs the harness, with the same `RAV_TOKEN` set:

```powershell
uv run rav readout              # registered boards
uv run rav readout --watch      # every board, once a second
uv run rav readout mw1-01       # one board's latest snapshot as JSON
```

| State | Meaning |
|---|---|
| `NO DATA` | nothing received since rav-server started |
| `FRESH 0.31s` | a snapshot arrived within 2 s; verdicts can use it |
| `STALE 5.20s` | the board stopped posting; a step on it would stop |

Open and close the microwave door, or the centrifuge lid, and watch the values change. That proves the whole path without moving the arm.

On the board's serial monitor, the `wifi` event value is the HTTP status of its last post:

| Value | Fix |
|---|---|
| `204` | working |
| `0` | no answer: wrong `RAV_HOST` or port, firewall, rav-server not running, or no `--device-host` (Route A) / tunnel down (Route B) |
| `401` | `DEVICE_NAME` isn't in `RAV_DEVICE_KEYS`, or `DEVICE_KEY` doesn't match its entry |
| `502` | Route B only: Vultr can't reach your laptop; check the tunnel client |

## Notes

- USB serial isn't a substitute here. These boards print event lines (`{"t":…,"ev":"door","v":1}`), not the flat snapshots `--readout serial` expects. Use WiFi.
- Short presses can fall between two snapshots. The firmware sends on every change, but a press shorter than one post round trip may be missed.
- On Route B, a tunnel drop can cut off an MCP call mid-step. Run `rav status` after it reconnects, before repeating anything.

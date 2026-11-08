# System 1 on a hotspot and System 2 on Vultr

System 1 and the appliances connect to the internet through the hotspot. Each appliance sends HTTPS snapshots to Vultr. Caddy forwards those POSTs through the outbound WebSocket tunnel to System 1, which owns the device registry and latest readings. System 2 uses the same tunnel to call System 1's existing Streamable HTTP MCP server.

```mermaid
flowchart LR
    Board["MC-6 and MW-1 boards"] -->|"HTTPS POST /readout/device-id"| Caddy["Vultr Caddy :443"]
    Caddy -->|"Publish only"| Relay["Vultr relay on loopback"]
    Harness["System 2 harness"] <-->|"MCP over HTTP"| Relay
    Client["System 1 tunnel client"] -->|"Opens WSS /tunnel"| Caddy
    Caddy <-->|"WebSocket"| Relay
    Client <-->|"Loopback TCP"| Server["System 1 MCP and readout"]
    Caddy -->|"HTTPS /"| Browser["Hosted demo files"]
```

The public endpoint acknowledges a snapshot only after System 1 accepts it. It returns an error when the tunnel is unavailable. After reconnecting, the boards resume sending their latest snapshots. The hosted browser console replays bundled runs. For current robot status or appliance data, use the harness on Vultr.

| Credential | Where it belongs | What it permits |
|---|---|---|
| Tunnel token | Relay and System 1 tunnel client | Register the outbound WebSocket |
| `RAV_TOKEN` | System 1 server and System 2 harness | Call the MCP tools, including robot routines |
| `RAV_DEVICE_KEYS` | System 1 server | Map board IDs to their individual readout credentials |
| `DEVICE_KEY` | One Arduino's ignored `arduino_secrets.h` | Publish only to that board's public readout route |

Keep the three types of credentials distinct. The public board and tunnel connections use TLS. Caddy only forwards POSTs on the public readout route. MCP and readout inspection are available through the private harness connection.

- [Firmware publisher](../../firmware/firmware/rav_wifi.h) sends snapshots with the board ID in the URL.
- [System 1 readout API](../../system-1/server/src/rav_server/device_api.py) validates the credential, ingests the snapshot and reports its age.
- [Tunnel client and relay](tunnel.py) carry the existing MCP HTTP traffic over one WebSocket. They forward TCP streams without interpreting MCP messages.
- [System 2 MCP client](../../system-2/harness/src/rav_harness/client.py) calls System 1 through the relay's loopback port.

## Vultr

1. Install Caddy 2.11 and Python 3.12 or 3.13. Allow inbound TCP 443 in the host and cloud firewalls. Open TCP 80 if you want the bare address to redirect to HTTPS or need the ACME HTTP challenge. Run System 2 on the VPS host so it can reach the relay's loopback listener.
2. Create a venv at `/opt/rav-tunnel` with `python3 -m venv /opt/rav-tunnel`. Copy `tunnel.py` into it and install `requirements.txt` with `/opt/rav-tunnel/bin/python -m pip install -r requirements.txt`. Put a generated random tunnel token (at least 32 URL-safe characters) in `/etc/rav/tunnel-token`, readable only by root. Install `rav-tunnel.service` under `/etc/systemd/system` and run `sudo systemctl daemon-reload` followed by `sudo systemctl enable --now rav-tunnel`.
3. Install the Caddyfile or add its site block to the existing configuration. Set `RAV_PUBLIC_HOST` in Caddy's service environment, validate the config with that variable set, then start or reload Caddy. Both relay listeners bind to loopback.
4. From `system-2`, run `uv sync --locked --no-dev`. The deployment checkout also needs `system-1/interface`, which System 2 uses for the wire contracts. Set `RAV_TOKEN` in the harness environment to the same value as on System 1.

For a DNS hostname, point its record at the VPS and let Caddy manage HTTPS. For a public IP, set `RAV_PUBLIC_HOST` to the IP and put this TLS block inside the Caddy site block. Caddy handles certificate renewal. The TLS-ALPN challenge needs TCP 443 to reach Caddy. [Let's Encrypt IP certificates](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)

```caddyfile
tls {
    issuer acme {
        profile shortlived
        disable_http_challenge
    }
}
```

### Browser console

From `system-2/console/web`, run `npm ci` and `VITE_CONSOLE_READ_ONLY=1 npm run build`. Install the contents of `dist/` under `/var/www/rav-console`. The hosted demo serves bundled projects and recorded runs. Live robot control and project writes require a separate authenticated backend.

## System 1

Copy the tunnel token into a private local file and set `RAV_TUNNEL_TOKEN_FILE` to its absolute path. From the repository root, run the client with `uv` or install `requirements.txt` into a dedicated Python environment and run the same script directly:

```powershell
uv run --no-project --with-requirements deploy/vultr/requirements.txt python deploy/vultr/tunnel.py client --url wss://robot.example.edu/tunnel
```

The client retries after a connection loss. A dropped connection can interrupt an in-flight MCP call. Check the robot's status after reconnecting before deciding whether to repeat a command.

Set `RAV_TOKEN` and `RAV_DEVICE_KEYS` in the System 1 server environment. The latter is a JSON object mapping each device ID to the corresponding Arduino's random 32–128 character URL-safe key. Start with the mock robot from `system-1`:

```powershell
uv run rav-server --robot mock --telemetry-port 0
```

For a supervised hardware run use `--robot real --arm-port COM5 --calibration <file> --readout http --readout-device mw1-01` with the actual port, calibration and device ID. The selected appliance supplies the real robot's readout. Other registered appliances remain available for inspection. System 1 must have a fresh snapshot before it can use the selected appliance's data.

A private lab can still use direct HTTP on a shared network. Start System 1 with `--device-host <System 1 LAN IP>` and set the board's `RAV_HOST` to that IP, `RAV_PORT` to 8782, and `RAV_USE_TLS` to 0. Keep this HTTP listener on the private network.

## Appliances

Both PlatformIO targets use an Arduino Uno R4 WiFi and the same snapshot publisher. Copy each board's example to `arduino_secrets.h` beside its sketch. The sketch enables Wi-Fi when that file exists.

| Board | PlatformIO target | Default example ID | Configuration |
|---|---|---|---|
| MC-6 centrifuge | `mc6` | `mc6-01` | [MC-6 secrets example](../../firmware/MC6_firmware/arduino_secrets.h.example) |
| MW-1 microwave | `mw1_r4_wifi` | `mw1-01` | [MW-1 secrets example](../../firmware/MW1_firmware/arduino_secrets.h.example) |

Set the hotspot SSID and password, the VPS TLS hostname, port 443, and `RAV_USE_TLS=1` in both files. Prefer a DNS name with a matching certificate for the boards. The Uno R4 WiFi uses the root CA bundle in its connectivity firmware. Give each board a distinct ID and key that match its own entry in `RAV_DEVICE_KEYS`. A serial `wifi` event with value `204` means System 1 accepted that board's snapshot. On Vultr, use `rav readout mc6-01` and `rav readout mw1-01` to verify both.

The firmware sends complete, flat JSON snapshots on changes and periodically. Short transitions can fall between sends. Wi-Fi joins and connection setup are synchronous calls with short timeouts. The firmware spaces out retries after an error so repeated attempts leave time for button and sensor polling.

Use the top-level `firmware/` PlatformIO project for both boards. On the MC-6, wire the tube sensor to **A1** and the lid sensor to **A2**. The current bench configuration uses the lid sensor and leaves the tube requirement disabled. Recalibrate after swapping the sensor pins, since saved thresholds are tied to the pin assignment.

## Smoke test

Open the Arduino serial monitor at **115200 baud**. With the current firmware, `wifi_link` reports whether the board joined the hotspot. A `wifi` event with value `204` confirms that System 1 accepted an HTTPS snapshot through Vultr. The firmware reports these events on changes, so reopen the monitor and reset the board if you missed startup. A value of `0` means the board got no usable HTTP response, `401` means System 1 rejected the device credential, and `502` usually means Vultr could not reach System 1.

On Vultr, run the live readout watcher with the same `RAV_TOKEN` used by the System 2 harness:

```sh
uv run rav readout --watch
uv run rav readout mw1-01 --watch   # one device
```

`NO DATA` means System 1 has received no snapshots since startup. `FRESH` means a snapshot arrived within the last two seconds. `STALE` shows the last known values and their age. With the microwave idle, open and close its door and check that `door` changes in the watcher. Then turn off the board and check that its reading becomes `STALE`. This tests the whole path without moving the arm.

From `system-2` on Vultr, with System 1 running in mock mode and the tunnel connected:

```sh
uv run rav status
uv run rav readout
uv run rav readout mc6-01
```

Send a test snapshot to the public HTTPS endpoint with the registered device credential, or power up the board.

```sh
curl -fsS "https://${RAV_PUBLIC_HOST}/readout/mc6-01" \
  -H "Authorization: Bearer ${MC6_KEY}" -H 'Content-Type: application/json' \
  --data '{"speed":1000,"lid":1,"LCD":"READY"}'
```

Run `uv run rav readout mc6-01` on Vultr. Expect `fresh: true` while a board is posting, and `false` after two seconds without updates. For a single manual POST, verify the sample values even if the CLI starts after the freshness window. The same key should receive 401 on a different device's POST route. Public `/mcp` and a GET to `/readout/mc6-01` should return 404. Stop the tunnel and confirm the public POST fails instead of returning 204. Reconnect and run `rav status` again.

| Symptom | Check |
|---|---|
| Browser shows the demo but live controls are unavailable | This is the static console. Use `rav status` and `rav readout` on Vultr for the live connection. |
| `rav status` cannot connect | Check `journalctl -u rav-tunnel -u caddy` on Vultr and the System 1 tunnel log. Verify the certificate, tunnel token, MCP token, and System 1's loopback listener. |
| Arduino gets no response | Check hotspot internet access, the board's TLS firmware and endpoint, and the System 1 tunnel log. |
| Arduino gets 401 | Verify the ID in the URL and its matching `RAV_DEVICE_KEYS` entry. |
| System 2 sees an old snapshot | Check `age_s` and `fresh`. System 1 retains the last sample for inspection and refuses stale Wi-Fi readings for real-arm verdicts. |

# System 2 on Vultr

System 1 and the appliances share a private hotspot. The appliances post snapshots directly to System 1 on port 8782. System 1 opens one outbound WSS connection to Vultr, where Caddy terminates TLS on 443 and exposes `/tunnel`. The relay forwards Vultr's `127.0.0.1:8780` to System 1's `127.0.0.1:8780` for the harness's existing Streamable HTTP MCP client.

## Vultr

1. Point a DNS hostname at the VPS. Allow TCP 80 and 443 for Caddy and certificate issuance. Install Caddy 2.11.9 and Python 3.12 or 3.13. Run System 2 directly on the VPS host so it can reach the loopback listener.
2. Create a venv at `/opt/rav-tunnel` with `python3 -m venv /opt/rav-tunnel`. Copy `tunnel.py` into it and install `requirements.txt` with `/opt/rav-tunnel/bin/python -m pip install -r requirements.txt`. Put a generated random tunnel token (at least 32 URL-safe characters) in `/etc/rav/tunnel-token`, readable only by root. Install `rav-tunnel.service` under `/etc/systemd/system` and run `sudo systemctl daemon-reload` followed by `sudo systemctl enable --now rav-tunnel`.
3. Install the Caddyfile or add its site block to the existing configuration. Set `RAV_PUBLIC_HOST` to the DNS hostname in Caddy's service environment, validate the config with that variable set, then start or reload Caddy. Both relay listeners bind to loopback.
4. Set `RAV_TOKEN` in the System 2 harness environment. It must match the token on System 1. Use a separate secret from the frp token and all device credentials.

## System 1

Copy the tunnel token into a private local file and set `RAV_TUNNEL_TOKEN_FILE` to its absolute path. From the repository root, run the client with `uv` or install `requirements.txt` into a dedicated Python environment and run the same script directly:

```powershell
uv run --no-project --with-requirements deploy/vultr/requirements.txt python deploy/vultr/tunnel.py client --url wss://robot.example.edu/tunnel
```

The client retries after a connection loss. A dropped connection can interrupt an in-flight MCP call. Check the robot's status after reconnecting before deciding whether to repeat a command.

Join the hotspot and find System 1's IPv4 address on that network. Set `RAV_TOKEN` and `RAV_DEVICE_KEYS` in the System 1 server environment. The latter is a JSON object mapping each stable device ID to its own random 32–128 character URL-safe credential. Start with the mock robot from `system-1`, substituting the actual address:

```powershell
uv run rav-server --robot mock --telemetry-port 0 --device-host 192.168.43.10
```

Allow inbound TCP 8782 on System 1 for the hotspot network if its firewall blocks it. The hotspot must allow its clients to talk to each other. If the hotspot changes System 1's address, update `--device-host` and the boards' `RAV_HOST`.

For a supervised hardware run keep `--device-host` and use `--robot real --arm-port COM5 --calibration <file> --readout http --readout-device mc6-01` with the actual port, calibration and device ID. The selected appliance supplies the real robot's readout. Other registered appliances remain available for inspection. System 1 must have a fresh snapshot before it can use the selected appliance's data.

## Appliances

For each board, copy [the secrets example](../../firmware/firmware/arduino_secrets.h.example) to `arduino_secrets.h` beside its sketch in `firmware/MC6_firmware` or `firmware/MW1_firmware`. Set the hotspot SSID and password, System 1's hotspot IP and port 8782, and that board's ID and credential. The board sends HTTP over the private hotspot, so keep that network password-protected and use credentials scoped to device readout. Use `mc6` and `mw1_r4_wifi` as the PlatformIO build and upload targets. A serial `wifi` event with value `204` means System 1 accepted the snapshot.

The firmware sends complete, flat JSON snapshots on changes and periodically. Short transitions can fall between sends. Joining Wi-Fi or opening a connection can block the firmware loop, especially during outages. Bench-check button and sensor timing with Wi-Fi enabled before using it in a run.

## Smoke test

From `system-2` on Vultr, with System 1 running in mock mode and the tunnel connected:

```sh
uv run rav status
uv run rav readout
uv run rav readout mc6-01
```

Send a test snapshot from a machine on the hotspot with the registered device credential, or power up the board:

```sh
curl -fsS "http://${SYSTEM1_HOTSPOT_IP}:8782/readout/mc6-01" \
  -H "Authorization: Bearer ${MC6_KEY}" -H 'Content-Type: application/json' \
  --data '{"speed":1000,"lid":1,"LCD":"READY"}'
```

Run `uv run rav readout mc6-01` on Vultr. Expect `fresh: true` while a board is posting, and `false` after two seconds without updates. For a single manual POST, verify the sample values even if the CLI starts after the freshness window. The same key should receive 401 on a different device's POST route. Public `/mcp` and `/readout/mc6-01` should return 404. Stop the tunnel and confirm the board still gets 204. Reconnect and run `rav status` again.

# Skua Dashboard (Windows)

A browser dashboard and local Python relay for Skua/VibeSkua.

## Start (Windows)

Run `start-gui.bat` to launch the desktop companion. It automatically starts the local relay if it is not already running; use **Open / Reload Dashboard** to open `http://localhost:8787` in your browser. The GUI uses Python's built-in Tkinter and does not need extra Python packages. The old standalone `start.bat` launcher has been removed so the GUI is the normal entry point.

- **Open / Reload Dashboard** opens the local dashboard in your default browser.
- **Restart Relay** restarts the local Python relay.
- **Fetch Latest Git Updates** runs `git pull --ff-only`; if updates are pulled, it restarts the relay so the new code is loaded.
- **Open Repository Folder** opens this checkout in File Explorer.

The GUI starts the relay automatically if it is not already reachable. Keep the companion open while you want it to manage the relay. The dashboard website itself remains unchanged.

### Manager window icon

The manager uses `SkuaIcon.ico` as its Windows title-bar/taskbar icon when the file is present in the repository folder. Download [SkuaIcon.ico](https://raw.githubusercontent.com/wtffidy/shit-yourself/main/SkuaIcon.ico) and save it beside `dashboard_gui.py` (the same folder as `start-gui.bat`), then close and reopen the manager. If the icon is missing, the manager falls back to the default Python/Tkinter icon.

The relay receives JSON payloads sent to the client's configured webhook URL. Character and log information can be displayed when the client includes those values in its payload.

## Normal Windows VibeSkua: equipment, quests, and live status

The default VibeSkua webhook service sends health pings, but the original health ping only contained a message—not a snapshot of the game state. The dashboard therefore had no equipment or quest values to display, and status-only pings did not refresh the dashboard's online timestamp.

This repository now contains a patched copy of the VibeSkua webhook service:

- [Patched `DiscordWebhookService.cs`](patches/DiscordWebhookService.cs)

To use it, replace `Skua.Core/Services/DiscordWebhookService.cs` in your **local Windows VibeSkua source checkout** with that file, build VibeSkua, and run the rebuilt client. This does not require Docker or Linux. The snapshot uses VibeSkua's existing `IScriptInterface` for character stats, equipped inventory items, and active quests; it does not add a separate API or token.

The VibeSkua source repository is read-only for this dashboard project, so this is provided as a copyable patch file rather than a commit to the VibeSkua repository.

The relay now treats every received webhook as a fresh online heartbeat while tracking `stateUpdated` separately, and it preserves prior state when a ping contains no state snapshot.



## Live updates with WebSockets

When the dashboard is opened from the relay on the same origin (including `http://<PC-LAN-IP>:8787/`), it connects to `/ws` and receives pushed snapshots when bot webhook data changes. Process usage is refreshed every two seconds while a browser is connected. The browser automatically reconnects if the connection drops. HTTP polling remains as a fallback when WebSockets are unavailable, including remote relay setups that do not expose the `/ws` endpoint.

WebSockets only make relay-to-browser updates immediate; the client still has to send telemetry to the relay first.

## VibeSkua process usage (Windows)

The local relay exposes `/usage` and the dashboard header displays the detected VibeSkua process's CPU usage, working-set RAM, process uptime, and the number of online dashboard tabs. CPU is sampled from Windows process times and may take two polls to appear. RAM is the total working set for matching VibeSkua/Skua processes.

These are **process-level** measurements. VibeSkua hosts multiple game tabs inside the same application process, so Windows does not provide reliable CPU or RAM attribution for each dashboard bot/tab from process counters alone. The active-tab count is based on dashboard bot heartbeats, not a separate measurement of the app's internal tab strip. The executable product version is read from Windows file metadata when available.

## Security and LAN access

The relay listens on `0.0.0.0:8787` by default so devices on your private network can reach it. Localhost requests on the PC continue to work without a read key. Requests from other devices must supply the generated `read_key` from `config.json`; enter it in the dashboard's **Settings → Read/access key** field. The webhook's separate `push_key` is not the read key and should not be shared.

For same-Wi-Fi access:

1. Run `ipconfig` in Command Prompt and find the active adapter's IPv4 address.
2. On your phone or another PC connected to the same trusted Wi-Fi, open `http://<PC-LAN-IP>:8787/`.
3. Open **Settings** and paste the `read_key` value from the dashboard folder's `config.json`.
4. If Windows Firewall prompts, allow Python only on **Private networks**. If you need to create a rule manually, scope it to your private LAN and TCP port 8787.

Use a long, private Wi-Fi password and do not forward port 8787 on your router. Avoid guest Wi-Fi for the phone because device isolation may block access. If you do not want LAN access, set `"host": "127.0.0.1"` in `config.json` and restart the relay.

## Mobile access (same Wi-Fi and away from home)

The dashboard is served locally at `http://localhost:8787/`.

### On the same home Wi-Fi

1. Find your Windows PC's LAN IPv4 address with `ipconfig` (look for the active Wi-Fi/Ethernet adapter's `IPv4 Address`).
2. For phone access, the dashboard server must listen on the LAN interface, not only `127.0.0.1`. If it is bound to localhost, a phone cannot reach it by using the PC's IP.
3. Create a Windows Firewall rule if needed (exact steps below), then open `http://<PC-LAN-IP>:8787/` on your phone and enter the `read_key` from `config.json` in Dashboard Settings.
4. Keep the PC and phone on the same Wi-Fi. Some guest Wi-Fi networks isolate devices and prevent this connection.

### Create the Windows Firewall rule manually

1. Press **Win + R**, type `wf.msc`, and press Enter.
2. Select **Inbound Rules** in the left pane.
3. Select **New Rule…** in the right pane.
4. Choose **Port** → **Next**.
5. Choose **TCP**, enter `8787` for **Specific local ports**, and click **Next**.
6. Choose **Allow the connection** → **Next**.
7. Check **Private** only. Leave **Public** and **Domain** unchecked → **Next**.
8. Name the rule `Skua Dashboard - Port 8787` and click **Finish**.

If possible, scope the rule's **Scope** tab to your local subnet as an additional restriction. If an existing broad Python firewall rule is already enabled, review it too; a narrower rule does not necessarily override a broader allow rule. Only allow access on a trusted private network. Do not create router port forwarding for port 8787.

Do not expose the webhook relay or port 8787 directly to the public internet.

### Away from home (private access with Tailscale)

1. Install [Tailscale for Windows](https://tailscale.com/download/windows) on the PC and the Tailscale app on your phone.
2. Sign in to the same tailnet on both devices.
3. With the dashboard running on port 8787, run this in PowerShell on the PC:

   ```powershell
   tailscale serve --bg 8787
   ```

4. Follow any prompts and open the HTTPS URL printed by Tailscale on your phone while Tailscale is connected.
5. Add that page to your phone's home screen for one-tap access.

Use **Tailscale Serve**, not Funnel, to keep the dashboard private to your tailnet. The PC, relay, dashboard, and Tailscale must remain running for remote access to work.

## Health ping / refresh interval

The patched VibeSkua service sends one dashboard snapshot immediately when a script starts. Repeated snapshots are controlled by VibeSkua's `WebhookPingInterval` client setting, measured in **minutes**.

- `0` (the default) disables recurring health pings, so you will see the initial snapshot but no later health updates.
- Set `WebhookPingInterval` to `1` for a snapshot every minute, or `2` for every two minutes.
- The timer only runs while a script is running; it stops when the script stops or errors.
- Rebuild and run the patched VibeSkua client after changing its source patch. A settings-only change generally requires restarting the script so the timer is started again.

WebSockets push each new snapshot to the dashboard immediately after the relay receives it; the VibeSkua client still needs to send snapshots periodically.

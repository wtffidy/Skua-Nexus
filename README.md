# Skua Dashboard (Windows)

A browser dashboard and local Python relay for Skua/VibeSkua.

## Start (Windows)

Run `start-gui.bat` to launch the desktop companion. It automatically starts the local relay if it is not already running; use **Open / Reload Dashboard** to open `http://localhost:8787` in your browser. The GUI uses Python's built-in Tkinter and does not need extra Python packages. The old standalone `start.bat` launcher has been removed so the GUI is the normal entry point.

- **Open / Reload Dashboard** opens the local dashboard in your default browser.
- **Restart Relay** restarts the local Python relay.
- **Fetch Latest Git Updates** runs `git pull --ff-only`; if updates are pulled, it restarts the relay so the new code is loaded.
- **Open Repository Folder** opens this checkout in File Explorer.

The GUI starts the relay automatically if it is not already reachable. Keep the companion open while you want it to manage the relay. The dashboard website itself remains unchanged.

The relay receives JSON payloads sent to the client's configured webhook URL. Character and log information can be displayed when the client includes those values in its payload.

## Normal Windows VibeSkua: equipment, quests, and live status

The default VibeSkua webhook service sends health pings, but the original health ping only contained a message—not a snapshot of the game state. The dashboard therefore had no equipment or quest values to display, and status-only pings did not refresh the dashboard's online timestamp.

This repository now contains a patched copy of the VibeSkua webhook service:

- [Patched `DiscordWebhookService.cs`](patches/DiscordWebhookService.cs)

To use it, replace `Skua.Core/Services/DiscordWebhookService.cs` in your **local Windows VibeSkua source checkout** with that file, build VibeSkua, and run the rebuilt client. This does not require Docker or Linux. The snapshot uses VibeSkua's existing `IScriptInterface` for character stats, equipped inventory items, and active quests; it does not add a separate API or token.

The VibeSkua source repository is read-only for this dashboard project, so this is provided as a copyable patch file rather than a commit to the VibeSkua repository.

The relay now treats every received webhook as a fresh online heartbeat while tracking `stateUpdated` separately, and it preserves prior state when a ping contains no state snapshot.

## Security

The relay binds to `127.0.0.1` by default. Keep it local unless you deliberately configure and secure remote access.

## Mobile access (same Wi-Fi and away from home)

The dashboard is served locally at `http://localhost:8787/`.

### On the same home Wi-Fi

1. Find your Windows PC's LAN IPv4 address with `ipconfig` (look for the active Wi-Fi/Ethernet adapter's `IPv4 Address`).
2. For phone access, the dashboard server must listen on the LAN interface, not only `127.0.0.1`. If it is bound to localhost, a phone cannot reach it by using the PC's IP.
3. Allow the dashboard port through Windows Firewall only on your **Private** network profile. Then open `http://<PC-LAN-IP>:8787/` on your phone.
4. Keep the PC and phone on the same Wi-Fi. Some guest Wi-Fi networks isolate devices and prevent this connection.

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

The dashboard can only refresh fields when a new webhook snapshot arrives. This is periodic polling, not a continuous real-time stream.

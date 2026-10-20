# Skua Dashboard (Windows)

A browser dashboard and local Python relay for Skua/VibeSkua.

## Start

Run `start.bat` on Windows. The dashboard is served at `http://localhost:8787`.

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

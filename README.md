# Skua Dashboard (Windows)

A small browser dashboard and local Python relay for Skua/VibeSkua.

## Start

Run `start.bat` on Windows. The dashboard is served at `http://localhost:8787`.
The relay keeps accepting the existing Discord-webhook payload format, so the
webhook-only setup continues to work without the live API integration.

## Live equipment and quest data

Discord webhook notifications do not necessarily include current equipment or
active quest progress. To display that data live, the relay can optionally read
the VibeSkua host API implemented by the [VibeSkua-Docker project](https://github.com/JenangMaker/VibeSkua-Docker).
This is an API integration, not a Linux/Docker requirement; the Skua/VibeSkua
instance must expose the compatible host API.

1. Configure the compatible VibeSkua host API to listen on `127.0.0.1:8789`
   (or the address/port you use).
2. Open `config.json` next to `relay.py`.
3. Set `vibeskua_url` to the host API base URL. If the API requires a token,
   set `vibeskua_token` to the same `SKUA_API_TOKEN` configured for that API.
4. Restart `start.bat` and refresh the dashboard.

Example configuration:

```json
{
  "port": 8787,
  "push_key": "",
  "discord_webhook": "",
  "allowed_origins": ["https://wtffidy.github.io"],
  "vibeskua_url": "http://127.0.0.1:8789",
  "vibeskua_token": ""
}
```

When `vibeskua_url` is configured, `GET /bots` reads live tabs and detailed
status from the API, including equipped items, active quests and requirement
progress, character/map values, combat target and script state. If it is blank,
`/bots` uses the saved webhook data as before.

The relay does not start or configure the VibeSkua API for you. If the client
you run does not expose `GET /status`, `GET /tabs`, and
`GET /tabs/{tab}/api/status?detail=1`, the live integration will return an
error; leave `vibeskua_url` blank to use webhook mode.

## Security

The relay binds to `127.0.0.1` by default. Do not expose the relay or the
VibeSkua control API to an untrusted network. Anyone who can reach an
unprotected control API may be able to control the running client.

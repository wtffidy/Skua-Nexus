# Skua Dashboard (Windows)

A browser dashboard and local Python relay for Skua/VibeSkua.

## Start

Run `start.bat` on Windows. The dashboard is served at `http://localhost:8787`.

The relay receives the JSON payloads sent to the client's Discord webhook URL. It can display character and log information that arrives in those payloads. It cannot discover live equipment or active quest progress unless the client sends those values or exposes a real supported interface for them.

## Current data limitation

The dashboard currently receives character and log data, but equipment and quest data are missing. Session notifications such as “Farming Session Concluded” only contain the fields included in that notification; the relay cannot infer the equipped items or active quests from a script name, gold earned, or elapsed time.

To fix this properly for normal Windows VibeSkua, we need to trace where the existing client watcher obtains character/log data and extend that same reporting path with equipment and quest data. If the client webhook payload does not contain those fields, the fix belongs in the watcher/client-side reporting code—not in a made-up API URL or token.

## Security

The relay binds to `127.0.0.1` by default. Keep it local unless you deliberately configure and secure remote access.

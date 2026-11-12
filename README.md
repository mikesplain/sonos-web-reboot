# Sonos Web Reboot for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Adds a **Restart** button for each Sonos speaker you select. Press it on the device page or call **Button: Press** from an automation. The restart request travels through the Sonos Web cloud service using your existing Sonos Web session.

Tested with Home Assistant Core 2026.10.0 and 2026.10.4, the two versions the CI matrix runs. Home Assistant Core 2026.11 is not covered yet: each `pytest-homeassistant-custom-component` release pins one Home Assistant version, and the newest one pins 2026.10.4.

- This is an unofficial community integration. It is not affiliated with, endorsed, or supported by Sonos.
- It uses a private Sonos Web endpoint that can change at any time without notice.
- The session cookie behaves like a sign-in credential. Treat it accordingly.

## Install with HACS

1. In HACS, open the menu (**⋮**) → **Custom repositories**. Add this repository URL with the category **Integration**:
   `https://github.com/mikesplain/sonos-web-reboot`
2. Search for **Sonos Web Reboot** in HACS and download it.
3. Restart Home Assistant to load the integration.

## Manual install

1. Download `sonos_web_reboot.zip` from the [latest release](https://github.com/mikesplain/sonos-web-reboot/releases/latest).
2. In your Home Assistant configuration directory, create `custom_components/sonos_web_reboot` and extract the zip into it so the result is `custom_components/sonos_web_reboot/manifest.json`. Preserve the `translations` folder.
3. Restart Home Assistant to load the integration.

## Get the Sonos Web session cookie

1. Open [Sonos Web](https://play.sonos.com) in your regular browser and sign in with the account that owns your system.
2. Open browser Developer Tools and select **Network**. Then run this read-only request from the Console on the Sonos Web page.

   ```js
   void fetch('/api/control/households')
   ```

3. Back in **Network**, open the `households` request and confirm it returned HTTP `200`. Under **Request Headers**, copy the full value of the `Cookie` header. The integration also accepts a `Cookie:` prefix. Copy the request header rather than using `document.cookie`, since the browser can keep session cookies out of JavaScript.
4. Paste it into the Home Assistant setup form below. Home Assistant stores it in the integration entry, which can be included in Home Assistant backups. Keep the cookie and any backups containing it private.

## Configure

1. In Home Assistant, open **Settings → Devices & services → Add integration** and search for **Sonos Web Reboot**.
2. Paste the cookie into the password field.
3. Choose your household if prompted, then select the speakers that should have restart buttons. Start with one speaker for your first test.

Each choice represents one player advertised by Sonos Web. For a home theater room, Sonos Web may list the soundbar and its bonded Sub or surrounds as one player. Only products advertised as separate players appear as separate choices. Playback group membership does not determine which player the button targets.

## Use

- Setup should show your real speaker names. Setup only reads your household and player list; it sends no control commands.
- Open the device created by Sonos Web Reboot and press **Restart** when a brief audio interruption is convenient. Confirm that the speaker disconnects and returns. An accepted HTTP request and Home Assistant's last-pressed timestamp alone cannot confirm a completed reboot.
- In an automation, choose **Button: Press** and target the intended restart button entity (created as `button.<speaker>_restart`). Each press sends one request.

## Behavior and troubleshooting

- A timeout, broken connection, or unusable server response can mean Sonos received the request anyway. The integration reports the uncertainty and blocks another attempt for that speaker for two minutes while the entry remains loaded. It does not retry. Confirm the speaker's state before trying again. A clear permission error is reported separately.
- When Sonos rejects the session as expired, Home Assistant offers **Reauthenticate**. Sign in again, copy the new header, and provide it in that flow. Your speaker selections and button entity IDs are retained. Session lifetime can vary; this integration requires manual cookie replacement when the session expires.
- Use **Reconfigure** on the integration entry to add or remove restart buttons. Before deselecting a speaker, check whether any automation targets its button.
- To uninstall, remove the **Sonos Web Reboot** integration entry in the UI, then remove its component directory, and restart Home Assistant.

## Optional command-line helper

`scripts/sonos-reboot.sh` sends the same requests from a terminal without Home Assistant. It is for testing only; the integration itself does not use it.

```sh
./scripts/sonos-reboot.sh check   RINCON_XXXXXXXXXXXXXXXX COOKIE_FILE
./scripts/sonos-reboot.sh reboot  RINCON_XXXXXXXXXXXXXXXX COOKIE_FILE
```

Find your own player ID in the Sonos Web Network panel: the `households` and `players` responses list each player's `id` value (format `RINCON_...`). Pass `-` as `COOKIE_FILE` to read the cookie value from stdin. Keep the cookie file private with permissions `600`.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the test environment, linting, and the release flow.

## License

MIT. See [LICENSE](LICENSE).

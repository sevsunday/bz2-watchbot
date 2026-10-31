# BZ2VSR WatchBot - Web Service

A Web Service that monitors multiplayer game data from [Battlezone II: Combat Commander](https://store.steampowered.com/app/624970/Battlezone_Combat_Commander/), curated specifically for VSR games hosted by the [BZ2 Vet Strat](https://discord.gg/FQnXFhnp) Discord community. Inspired by [bz2vsr.com](https://github.com/bz2vsr/bz2vsr.github.io).

Relies on the MultiplayerSessionList API by Nielk1 ([Github](https://github.com/Nielk1) | [Twitter](https://x.com/nielk1)).

![image](https://github.com/user-attachments/assets/29bbdbdc-c271-417f-a575-76ae5a03d94a)

## Technical Details

- Uses Discord Webhooks for communication
- Polls the BZ2 multiplayer API at configurable intervals
- Maintains session history for accurate status tracking
- Handles both Steam and GOG player identifiers
- Includes enhanced VSR map data

## Requirements

- Python 3.7+
- python-dotenv
- aiohttp
- watchdog

## Installation

**WARNING:** add your `.env` file to `.gitignore` to avoid exposing your webhook URL. Anyone with your webhook URL can post to your channel.

1. Clone or download this repository.
2. Install dependencies with `pip install -r requirements.txt`
3. Create a file called `.env` in the root directory and add this line `DISCORD_WEBHOOK_URL=<your_webhook_url>`
4. Configure the `notification_tag` for each webhook in `DISCORD_WEBHOOKS` and the `MONITORED_STEAM_IDS` list in `config.py` to fit your needs.
5. Run the bot `python main.py`

To run the tests (no network or Discord access needed), run `python -m unittest discover -s tests` from the repository root.

**NOTE:** `run.py` runs `main.py` in a wrapper that will automatically reload the bot if any changes are made to the code. This is useful for local development, and may also be useful in production depending on your server setup.

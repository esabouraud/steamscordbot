# steamscordbot

[![pypi status](https://github.com/esabouraud/steamscordbot/workflows/pypi/badge.svg)](https://github.com/esabouraud/steamscordbot/actions?query=workflow%3Apypi)
[![docker status](https://github.com/esabouraud/steamscordbot/workflows/docker/badge.svg)](https://github.com/esabouraud/steamscordbot/actions?query=workflow%3Adocker)

Discord Bot written in Python 3.8 using the [Steamworks Web API](https://partner.steamgames.com/doc/webapi) to provide Steam user data through chat commands.

It depends on:

- [steam](https://github.com/ValvePython/steam)
- [discord.py](https://github.com/Rapptz/discord.py)

## Features

- Resolve a vanity URL name into a Steam ID and display name
- List rarest or latest achievements of a public Steam profile
- List games most owned or recently played by friends of a public Steam profile

## Prerequisites

- Get a Steam API key : <https://steamcommunity.com/dev/apikey>
- Get a Discord Bot Token : <https://discord.com/developers/applications>

## Installation

### With pip

```sh
pip install steamscordbot
```

### With Docker

```sh
docker pull esabouraud/steamscordbot
```

### From source

```sh
git clone https://github.com/esabouraud/steamscordbot.git
cd steamscordbot
```

Then

```sh
pip install -U -r requirements.txt
```

Or

```sh
docker build -t esabouraud/steamscordbot .
```

## Run

### Generic

```sh
python -m steamscordbot --steam-apikey=<Steam API key> --discord-token=<Discord Bot Token>
```

The CLI arguments can also be passed as environment variables (useful when running in a container hosted by a cloud service provider).
The CLI arguments override the corresponding environment variables when both are available.

### Windows

```sh
set STEAM_APIKEY=<Steam API key>
set DISCORD_TOKEN=<Discord Bot Token>
py -3 -m steamscordbot
```

### Linux (Bash)

```sh
export STEAM_APIKEY=<Steam API key>
export DISCORD_TOKEN=<Discord Bot Token>
python3 -m steamscordbot
```

### Docker

```sh
docker run -d -e STEAM_APIKEY=<Steam API key> -e DISCORD_TOKEN=<Discord Bot Token> --restart=unless-stopped --name steamscord esabouraud/steamscordbot
```

## Usage

Use discord to send a message to the bot or to a text channel it is present on.

The bot command prefix is: `!$`

A Steam user is identified by either:

- his unique steamid (e.g. **76561197971216318** in <https://steamcommunity.com/profiles/76561197968052866>)
- his custom url (e.g. **gaben** in <https://steamcommunity.com/id/gaben>)

Supported commands are:

- **achievements**: Get achievements of a Steam user
- **check**: Perform a simple Steam API availability check
- **friends**: Get most owned or recently played games among friends of a profile
- **help**: Shows help message
- **profile**: Get profile info based on provided Steam vanity URL or steamid

Samples:

- `!$check`
- `!$profile gaben`
- `!$achievements gaben rarest`
- `!$achievements 76561197968052866 latest`
- `!$friends gaben list 5`
- `!$friends 76561197968052866 owned 15`
- `!$friends 76561197968052866 recent`

## TODO

- ~~list Discord users on server that have linked their Steam accounts (+ mention friends if caller has linked his steam account)~~
  - cannot be done, see limitations below.
- List rarest or latest badges of a public Steam profile
- List badges most owned or recently obtained by friends of a public Steam profile
- make it a proper chatbot with NLP ?

## Limitations

The [User.profile()](https://discordpy.readthedocs.io/en/stable/api.html#discord.User.profile) Discord API is forbidden to bots.
This means the bot cannot leverage the Steam connected account even when it is available.

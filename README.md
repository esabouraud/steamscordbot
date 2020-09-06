# steamscordbot

Discord Bot written in Python 3.8 giving access to Steam Web API through chat commands.

## Features

- Resolve a vanity URL name into a Steam ID
- List rarest or latest achievements of a public Steam profile

## TODO

- ~~list Discord users on server that have linked their Steam accounts (+ mention friends if caller has linked his steam account)~~
  - cannot be done, see limitations below.
- display Steam user information and status ~~from Discord name if linked~~ or from Steam vanity url name
- explore the Steam Web API for ideas : <https://partner.steamgames.com/doc/webapi>
  - list items on sale in marketplace
- make it a proper chatbot with NLP ?

## Limitations

The [User.profile()](https://discordpy.readthedocs.io/en/stable/api.html#discord.User.profile) Discord API is forbidden to bots.
This means the bot cannot leverage the Steam connected account even when it is available.

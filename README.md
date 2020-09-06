# steamscordbot

Using the Steam Web API for happy fun times in Discord.

## Features

## TODO

- list Discord users on server that have linked their Steam accounts (+ mention friends if caller has linked his steam account)
- display Steam user information and status from Discord name if linked or from Steam vanity url name
- explore the Steam Web API for ideas : <https://partner.steamgames.com/doc/webapi>
  - list rarest achievements
  - list items on sale in marketplace
- make it a proper chatbot with NLP ?

## Limitations

The [User.profile()](https://discordpy.readthedocs.io/en/stable/api.html#discord.User.profile) Discord API is forbidden to bots.
This means the bot cannot leverage the Steam connected account even when it is available.

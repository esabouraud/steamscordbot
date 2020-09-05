"""Discord bot calling Steam Web API on command"""

import os
import functools
import concurrent.futures
from steam.webapi import WebAPI
from discord.ext.commands import Bot


bot = Bot("!$")
steam_apikey = None


def call_steamapi(*args, **kwargs):
    """Perform Steam API call"""
    api = WebAPI(key=args[0])
    return api.call(args[1], **kwargs)


async def call_steamapi_async(method_path, **kwargs):
    """Wrap Steam API calls to make them async-compatible"""
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return await bot.loop.run_in_executor(pool, functools.partial(
            call_steamapi, steam_apikey, method_path, **kwargs))


@bot.command()
async def check(ctx):
    """Perform a simple Steam API availability check"""
    server_info = await call_steamapi_async(
        'ISteamWebAPIUtil.GetServerInfo')
    #print(server_info)
    await ctx.send(server_info)


@bot.command()
async def profile(ctx, vanity_name):
    """Get profile info based on Steam vanity URL"""
    vanity_url = await call_steamapi_async(
        'ISteamUser.ResolveVanityURL', vanityurl=vanity_name, url_type=1)
    #print(vanity_url)
    await ctx.send(vanity_url)


@bot.event
async def on_ready():
    """Finalize bot connection to Discord"""
    print("We have logged in as {0.user}".format(bot))


def main():
    """Launch bot"""
    global steam_apikey
    steam_apikey = os.environ["STEAM_APIKEY"]
    discord_token = os.environ["DISCORD_TOKEN"]
    try:
        bot.run(discord_token)
    except KeyboardInterrupt:
        print("bot stopping on its own")


if __name__ == "__main__":
    main()

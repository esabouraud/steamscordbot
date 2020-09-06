"""Discord bot calling Steam Web API on command"""

import os
import re
import functools
import concurrent.futures
import requests
from steam.webapi import WebAPI
import discord.ext.commands


PROFILE_RX = re.compile(r"^\d+$")
bot = discord.ext.commands.Bot("!$")
steam_apikey = None
discord_steam_map = {}


def call_steamapi(*args, **kwargs):
    """Perform Steam API call"""
    api = WebAPI(key=args[0])
    return api.call(args[1], **kwargs)


async def call_steamapi_async(method_path, **kwargs):
    """Wrap Steam API calls to make them async-compatible"""
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return await bot.loop.run_in_executor(pool, functools.partial(
            call_steamapi, steam_apikey, method_path, **kwargs))


def is_registered():
    async def predicate(ctx):
        if ctx.message.author.id in discord_steam_map:
            return True
        else:
            await ctx.send("Please register a Steam vanity URL")
            return False
    return discord.ext.commands.check(predicate)


def has_vanity_name(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        vanity_name = ctx = args[1]
        if vanity_name is None:
            ctx = args[0]
            await ctx.send("Please provide a Steam vanity URL")
            return
        return await func(*args, **kwargs)
    return wrapper


@bot.command()
async def check(ctx):
    """Perform a simple Steam API availability check"""
    server_info = await call_steamapi_async(
        "ISteamWebAPIUtil.GetServerInfo")
    await ctx.send(server_info)


async def profile_impl(ctx, vanity_name):
    """Implementation of profile retrieval"""
    vanity_url = await call_steamapi_async(
        "ISteamUser.ResolveVanityURL", vanityurl=vanity_name, url_type=1)
    await ctx.send(vanity_url)


@bot.command()
@has_vanity_name
async def profile(ctx, vanity_name=None):
    """Get profile info based on provided Steam vanity URL"""
    await profile_impl(ctx, vanity_name)


@bot.command()
@is_registered()
async def my_profile(ctx):
    """Get profile info based on registered Steam vanity URL"""
    vanity_name = discord_steam_map[ctx.message.author.id]
    await profile_impl(ctx, vanity_name)


async def achievements_impl(ctx, vanity_name, criteria):
    """Implementation of achievements retrieval"""
    if (m := PROFILE_RX.match(vanity_name)) is None:
        vanity_response = await call_steamapi_async(
            "ISteamUser.ResolveVanityURL", vanityurl=vanity_name, url_type=1)
        if vanity_response["response"]["success"] != 1:
            await ctx.send("Error resolving Steam vanity URL: %s" % vanity_name)
            return
        steamid = vanity_response["response"]["steamid"]
    else:
        # Turns out the vanity name was in fact a steamid (only digits)
        steamid = vanity_name
    owned_games_response = await call_steamapi_async(
        "IPlayerService.GetOwnedGames", steamid=steamid, include_appinfo=True,
        include_played_free_games=False, appids_filter=None, include_free_sub=False)
    if owned_games_response["response"]["game_count"] < 0:
        await ctx.send("Error fetching owned games for steamid: %s" % steamid)
        return
    print("%s owns %d games" % (steamid, owned_games_response["response"]["game_count"]))
    played_appids = [
        game["appid"]
        for game in owned_games_response["response"]["games"]
        if game["playtime_forever"] > 0]
    print("%s has played %d games" % (steamid, len(played_appids)))
    appids_names = {
        game["appid"]: game["name"]
        for game in owned_games_response["response"]["games"]
    }
    global_achievements_percentages = []
    for appid in played_appids:
        try:
            player_achievements_response = await call_steamapi_async(
                "ISteamUserStats.GetPlayerAchievements", steamid=steamid, appid=appid)
        except requests.exceptions.HTTPError:
            # FIXME find an API call to check that a game has achievements instead
            continue
        if "achievements" not in player_achievements_response["playerstats"]:
            continue
        player_obtained_achievements = [
            achievement["apiname"]
            for achievement in player_achievements_response["playerstats"]["achievements"]
            if achievement["achieved"] == 1]
        global_achievements_response = await call_steamapi_async(
            "ISteamUserStats.GetGlobalAchievementPercentagesForApp", gameid=appid)
        if "achievements" not in global_achievements_response["achievementpercentages"]:
            continue
        global_achievements_percentages.extend([
            {"appid": appid, "name": achievement["name"], "percent": achievement["percent"]}
            for achievement in global_achievements_response["achievementpercentages"]["achievements"]
            if achievement["name"] in player_obtained_achievements])
    sorted_global_achievements_percentages = sorted(
        global_achievements_percentages, key=lambda x: x["percent"])
    print("The 20 rarest achievements owned by %s are: %s" % (
        steamid,
        "\n\t".join(
            "%s %s (%f %%)" % (appids_names[achievement["appid"]], achievement["name"], achievement["percent"])
            for achievement in sorted_global_achievements_percentages[:20])
    ))

    #print(player_achievements_response)


@bot.command()
@has_vanity_name
async def achievements(ctx, vanity_name=None, criteria=None):
    """Get profile info based on provided Steam vanity URL"""
    await achievements_impl(ctx, vanity_name, criteria)


@bot.command()
@is_registered()
async def my_achievements(ctx, criteria):
    """Get profile info based on registered Steam vanity URL"""
    vanity_name = discord_steam_map[ctx.message.author.id]
    await achievements_impl(ctx, vanity_name, criteria)


@bot.command()
@has_vanity_name
async def register(ctx, vanity_name=None):
    """Register caller Steam profile with the bot"""
    discord_steam_map[ctx.message.author.id] = vanity_name
    await ctx.send("Steam profile registered (temporarily)")


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

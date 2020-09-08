"""Discord bot calling Steam Web API on command"""

import os
import re
import datetime
import functools
import concurrent.futures
from multiprocessing.pool import ThreadPool
import requests
from steam.webapi import WebAPI
import discord.ext.commands

# A regex to determine if a input looks like a SteamId
PROFILE_RX = re.compile(r"^\d+$")
ACHIEVEMENT_RAREST = "rarest"
ACHIEVEMENT_LATEST = "latest"
ACHIEVEMENT_CRITERIA = [ACHIEVEMENT_RAREST, ACHIEVEMENT_LATEST]

# The main bot discord client object
bot = discord.ext.commands.Bot("!$")
# The API key to use when performing calls to the Steamworks Web API
STEAM_APIKEY = None


def call_steamapi(*args, **kwargs):
    """Perform Steam API call"""
    api = WebAPI(key=args[0])
    return api.call(args[1], **kwargs)


async def call_steamapi_async(method_path, **kwargs):
    """Wrap Steam API calls to make them async-compatible"""
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return await bot.loop.run_in_executor(pool, functools.partial(
            call_steamapi, STEAM_APIKEY, method_path, **kwargs))


def has_vanity_name(func):
    """Decorator checking whether a command has been provided a vanity_name value"""
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


@bot.command()
@has_vanity_name
async def profile(ctx, vanity_name=None):
    """Get profile info based on provided Steam vanity URL"""
    vanity_url = await call_steamapi_async(
        "ISteamUser.ResolveVanityURL", vanityurl=vanity_name, url_type=1)
    await ctx.send(vanity_url)


def get_player_achievements_with_percentages_from_appid(steamid, appid):
    """Get a list of achivements obtained by a player in a game, with the global obtention percentages"""
    # Try to get player's achievements for a game (can fail if the game has no achievement support)
    try:
        player_achievements_response = call_steamapi(
            STEAM_APIKEY, "ISteamUserStats.GetPlayerAchievements", steamid=steamid, appid=appid, l="english")
    except requests.exceptions.HTTPError:
        # FIXME find an API call to check that a game has achievements instead
        #print("HTTPError: {0}".format(err))
        return []
    if "achievements" not in player_achievements_response["playerstats"]:
        return []
    player_obtained_achievements = {
        achievement["apiname"]: (achievement["unlocktime"], achievement["name"])
        for achievement in player_achievements_response["playerstats"]["achievements"]
        if achievement["achieved"] == 1}
    # Get the global achievements percentages for the game
    global_achievements_response = call_steamapi(
        STEAM_APIKEY, "ISteamUserStats.GetGlobalAchievementPercentagesForApp", gameid=appid)
    if "achievements" not in global_achievements_response["achievementpercentages"]:
        return []
    # Add the global achievements percentages to the user's list of obtained achievements
    return [
        {
            "appid": appid, "apiname": achievement["name"], "percent": achievement["percent"],
            #"name": player_obtained_achievements[achievement["name"]][1],
            "unlocktime": player_obtained_achievements[achievement["name"]][0]}
        for achievement in global_achievements_response["achievementpercentages"]["achievements"]
        if achievement["name"] in player_obtained_achievements]


def get_player_achievements_with_percentages(steamid, played_appids):
    """Get a list of achivements obtained by a player in multiple games, enriched with global obtention percentages"""
    # The Steam API will be called synchronously twice per game, so this can be pretty slow
    # Improve things by running the calls with a pool of threads
    pool = ThreadPool(10)
    player_achievements_with_percentages = pool.starmap(
        get_player_achievements_with_percentages_from_appid,
        [(steamid, appid) for appid in played_appids])
    # Consolidate the per-game list of achievements into a single global list
    global_achievements_percentages = []
    for player_achievements in player_achievements_with_percentages:
        global_achievements_percentages.extend(player_achievements)
    return global_achievements_percentages


async def achievements_check_input(ctx, vanity_or_steamid, criteria, max_count_str):
    """Analyze achievement command input parameters"""
    # Check if achievement sorting criteria is supported
    if criteria is None:
        await ctx.send("Please provide an achievement sorting criteria (available: %s)" % (
            ", ".join(ACHIEVEMENT_CRITERIA)
        ))
        return None
    if criteria not in ACHIEVEMENT_CRITERIA:
        await ctx.send("Unrecognized achievement sorting criteria: %s (available: %s)" % (
            criteria, ", ".join(ACHIEVEMENT_CRITERIA)
        ))
        return None
    max_count = 0
    try:
        max_count = int(max_count_str)
    except ValueError:
        await ctx.send("Achievement count must be an integer (%s)" % max_count_str)
        return None
    # Decide whether player is identified by vanity URL or SteamId
    if PROFILE_RX.match(vanity_or_steamid) is None:
         # Vanity URL provided, resolve it into a SteamId
        vanity_response = await call_steamapi_async(
            "ISteamUser.ResolveVanityURL", vanityurl=vanity_or_steamid, url_type=1)
        if vanity_response["response"]["success"] != 1:
            await ctx.send("Error resolving Steam vanity URL: %s" % vanity_or_steamid)
            return None
        steamid = vanity_response["response"]["steamid"]
    else:
        # SteamId (only digits) provided, use it directly
        steamid = vanity_or_steamid
    return steamid, max_count


def check_achievement_details(achievement_details):
    """Steam API apparently does not guarantee an achievement has a description"""
    if "description" in achievement_details:
        description = achievement_details["description"]
    else:
        description = ""
    return (achievement_details["displayName"], achievement_details["icon"], description)


def get_achievement_details_from_appid(achievement, game_name):
    """Get the details of a single achievement"""
    schema_game = call_steamapi(
        STEAM_APIKEY, "ISteamUserStats.GetSchemaForGame", appid=achievement["appid"])
    achievements_dict = {
        achievement_details["name"]: check_achievement_details(achievement_details)
        for achievement_details in schema_game["game"]["availableGameStats"]["achievements"]}
    return {
        # gameName cannot be used reliably, lots of ValveTestAppXXXXXX returned
        #"game_name": schema_game["game"]["gameName"],
        "appid": achievement["appid"],
        "game_name": game_name,
        "name": achievements_dict[achievement["apiname"]][0],
        "icon": achievements_dict[achievement["apiname"]][1],
        "description": achievements_dict[achievement["apiname"]][2],
        "unlocktime": achievement["unlocktime"],
        "percent": achievement["percent"]
    }


def get_achievements_details(achievements_list, appids_names):
    """Get the details of a list of achievements"""
    pool = ThreadPool(10)
    return pool.starmap(
        get_achievement_details_from_appid,
        [(achievement, appids_names[achievement["appid"]]) for achievement in achievements_list])


@bot.command()
@has_vanity_name
async def achievements(ctx, vanity_or_steamid=None, criteria=None, max_count_str="10"):
    """Get achievments based on vanity url or steam id"""
    if (inputs := await achievements_check_input(ctx, vanity_or_steamid, criteria, max_count_str)) is None:
        return
    steamid = inputs[0]
    max_count = inputs[1]
    # Get a list of games owned by the player
    owned_games_response = await call_steamapi_async(
        "IPlayerService.GetOwnedGames", steamid=steamid, include_appinfo=True,
        include_played_free_games=False, appids_filter=None, include_free_sub=False)
    if owned_games_response["response"]["game_count"] < 0:
        await ctx.send("Error fetching owned games for steamid: %s" % steamid)
        return
    owned_games_count = owned_games_response["response"]["game_count"]
    print("%s owns %d games" % (steamid, owned_games_count))
    if owned_games_count == 0:
        return
    # Restrict the list of owned games to ones that have been played
    played_appids = [
        game["appid"]
        for game in owned_games_response["response"]["games"]
        if game["playtime_forever"] > 0]
    if len(played_appids) != 0:
        print("%s has played %d games" % (steamid, len(played_appids)))
    else:
        # Some people restrict visibility of their play time, fallback to all owned games
        played_appids = [game["appid"] for game in owned_games_response["response"]["games"]]
    await ctx.send(
        "Please wait while achievement data of %d games is being collected" % len(played_appids))
    # Keep around a dictionary of AppIds: Game Names for nice display later on
    appids_names = {
        game["appid"]: game["name"]
        for game in owned_games_response["response"]["games"]
    }

    # Check that the player has allowed public access to his achievements
    try:
        call_steamapi(
            STEAM_APIKEY, "ISteamUserStats.GetPlayerAchievements", steamid=steamid, appid=played_appids[0], l="english")
    except requests.exceptions.HTTPError as err:
        # FIXME find an API call to check that a player has given access to his achievements instead
        #print("HTTPError: {0}".format(err))
        if err.response.status_code == 403:
            await ctx.send("Error fetching achievement data:\n`%s`" % (err.response.text))
            return

    # Do the heavy lifting in a separate thread: lots of synchronous calls to the Steam API to be done
    with concurrent.futures.ThreadPoolExecutor() as pool:
        global_achievements_percentages = await bot.loop.run_in_executor(pool, functools.partial(
            get_player_achievements_with_percentages, steamid, played_appids))

    if criteria == ACHIEVEMENT_RAREST:
        # Sort the list of achievements owned by the player by increasing global obtention percentage
        sorted_global_achievements = sorted(
            global_achievements_percentages, key=lambda x: x["percent"])
    elif criteria == ACHIEVEMENT_LATEST:
        # Sort the list of achievements owned by the player by decreasing unlock date
        sorted_global_achievements = sorted(
            global_achievements_percentages, reverse=True, key=lambda x: x["unlocktime"])

    # Get achievement details for nice display
    with concurrent.futures.ThreadPoolExecutor() as pool:
        sorted_global_achievements_head = await bot.loop.run_in_executor(pool, functools.partial(
            get_achievements_details, sorted_global_achievements[:max_count], appids_names))

    output_header = "The %d %s achievements owned by %s are:" % (
        len(sorted_global_achievements_head), criteria, steamid)
    output_lines = [
        "**%s** *%s* (unlocked: %s, global: %.2f%%)" % (
            achievement["game_name"], achievement["name"],
            datetime.datetime.fromtimestamp(achievement["unlocktime"]).isoformat(),
            achievement["percent"])
        for achievement in sorted_global_achievements_head]
    output_lines.insert(0, output_header)
    print("\n\t".join(output_lines))

    # Use embeds for fancy achievement display
    await ctx.send(output_header)
    for achievement in sorted_global_achievements_head:
        embed = discord.Embed(
            title=achievement["name"], type="rich",
            url="https://steamcommunity.com/profiles/%s/stats/%s" % (steamid, achievement["appid"]))
        embed.set_thumbnail(url=achievement["icon"])
        embed.add_field(name="Game", value=achievement["game_name"], inline=False)
        embed.add_field(name="Unlocked", value=datetime.datetime.fromtimestamp(achievement["unlocktime"]).isoformat())
        embed.add_field(name="% of all players", value="%.2f" % achievement["percent"])
        embed.set_footer(text=achievement["description"])
        await ctx.send(embed=embed)


@bot.event
async def on_ready():
    """Finalize bot connection to Discord"""
    print("We have logged in as {0.user}".format(bot))


def main():
    """Launch bot"""
    global STEAM_APIKEY
    STEAM_APIKEY = os.environ["STEAM_APIKEY"]
    discord_token = os.environ["DISCORD_TOKEN"]
    try:
        bot.run(discord_token)
    except KeyboardInterrupt:
        print("bot stopping on its own")


if __name__ == "__main__":
    main()

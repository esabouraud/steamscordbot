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
FRIENDS_LIST = "list"
FRIENDS_OWNED = "owned"
FRIENDS_RECENT = "recent"
FRIENDS_SUBCOMMANDS = ["list", "owned", "recent"]

# The main bot discord client object
bot = discord.ext.commands.Bot("!$", activity=discord.Game("!$help"))
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
        vanity_name = args[1]
        if vanity_name is None:
            ctx = args[0]
            await ctx.send("Please provide a Steam vanity URL or steamid")
            return
        return await func(*args, **kwargs)
    return wrapper


async def get_steamid(ctx, vanity_or_steamid):
    """Decide whether player is identified by vanity URL or SteamId"""
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
    return steamid


async def get_player_summary(steamid):
    """Fetch single player summary by steamid"""
    playersummaries_response = await call_steamapi_async(
        "ISteamUser.GetPlayerSummaries", steamids=steamid)
    if (
            "response" not in playersummaries_response
            or "players" not in playersummaries_response["response"]
            or len(playersummaries_response["response"]["players"]) == 0):
        return None
    return playersummaries_response["response"]["players"][0]


def format_player_embed(friend):
    """Return a player summary exported as discord Embed object"""
    embed = discord.Embed(
        title=friend["personaname"], type="rich", url=friend["profileurl"])
    embed.set_thumbnail(url=friend["avatarmedium"])
    if "gameextrainfo" in friend:
        friend_status = "In-game: %s" % friend["gameextrainfo"]
    elif friend["personastate"] != 0:
        friend_status = "Online"
    else:
        friend_status = "Offline"
    embed.add_field(name="Status", value=friend_status, inline=False)
    embed.add_field(name="steamid", value=friend["steamid"], inline=True)
    # Add "last seen online" footer for offline friends
    if friend["personastate"] == 0:
        if "lastlogoff" in friend:
            friend_last_logoff = datetime.datetime.fromtimestamp(friend["lastlogoff"]).isoformat()
        else:
            friend_last_logoff = "Unknown"
        embed.set_footer(text="Last online: %s" % friend_last_logoff)
    return embed


@bot.command()
async def check(ctx):
    """Perform a simple Steam API availability check"""
    server_info = await call_steamapi_async(
        "ISteamWebAPIUtil.GetServerInfo")
    await ctx.send(server_info)


@bot.command()
@has_vanity_name
async def profile(ctx, vanity_or_steamid=None):
    """Get profile info based on provided Steam vanity URL or steamid"""
    if (steamid := await get_steamid(ctx, vanity_or_steamid)) is None:
        return
    if (player := await get_player_summary(steamid)) is None:
        await ctx.send("Error fetching player summary")
        return
    await ctx.send(embed=format_player_embed(player))


def get_player_achievements_with_percentages_from_appid(steamid, appid):
    """Get a list of achievements obtained by a player in a game, with the global obtention percentages"""
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
    # Try to parse achievement maximum count
    max_count = 0
    try:
        max_count = int(max_count_str)
    except ValueError:
        await ctx.send("Achievement count must be an integer (%s)" % max_count_str)
        return None
    return await get_steamid(ctx, vanity_or_steamid), max_count


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


async def friends_check_input(ctx, vanity_or_steamid, subcommand, max_count_str):
    """Analyze friends command input parameters"""
    # Check if achievement sorting criteria is supported
    if subcommand is None:
        await ctx.send("Please provide a friends subcommand (available: %s)" % (
            ", ".join(FRIENDS_SUBCOMMANDS)
        ))
        return None
    if subcommand not in FRIENDS_SUBCOMMANDS:
        await ctx.send("Unrecognized friends subcommand: %s (available: %s)" % (
            subcommand, ", ".join(ACHIEVEMENT_CRITERIA)
        ))
        return None
    # Try to parse achievement maximum count
    max_count = 0
    try:
        max_count = int(max_count_str)
    except ValueError:
        await ctx.send("Achievement count must be an integer (%s)" % max_count_str)
        return None
    return await get_steamid(ctx, vanity_or_steamid), max_count


async def friends_list(ctx, player, max_count, friendslist):
    """Display steam profiles previews of friends"""
    await ctx.send("The Steam friends of player %s are (max. count %d):" % (player["personaname"], max_count))
    # Sort friendlist: ingame alphabetically, then online alphabetically, finally offline reverese chronologically
    sorted_friendlist = sorted(
        friendslist, key=lambda friend: (
            # False when friend is in-game: will be at the start of the list
            "gameextrainfo" not in friend,
            # False when friend is online: will be after in-game in list
            friend["personastate"] == 0,
            # 0 for in-game or online friends : no effect on list order for those
            # -1*lastlogoff for offline friends: last seen comes first in list
            -friend["lastlogoff"] if "lastlogoff" in friend else 0,
            # Alphabetical sort for in-game and online friends
            friend["personaname"]))
    # Use embeds for fancy friends display
    for friend in sorted_friendlist[:max_count]:
        await ctx.send(embed=format_player_embed(friend))


def get_games_owned_by_player(player):
    """Get the list of games owned by a single player"""
    owned_games_response = call_steamapi(
        STEAM_APIKEY, "IPlayerService.GetOwnedGames", steamid=player["steamid"], include_appinfo=True,
        include_played_free_games=False, appids_filter=None, include_free_sub=False)
    if "game_count" not in owned_games_response["response"] or owned_games_response["response"]["game_count"] <= 0:
        return player["steamid"], []
    return player["steamid"], owned_games_response["response"]["games"]


def get_games_owned_by_players(playerslist):
    """Build a a list of games owned by players"""
    # Get a list of tuples (player, list of of games)
    pool = ThreadPool(10)
    return pool.map(get_games_owned_by_player, playerslist)


async def friends_owned(ctx, player, max_count, playerslist):
    """Display games most owned among a list of players"""
    # Do the slow part in a separate thread: one synchronous call per player to the Steam API to be done
    with concurrent.futures.ThreadPoolExecutor() as pool:
        steamid_games_list = await bot.loop.run_in_executor(pool, functools.partial(
            get_games_owned_by_players, playerslist))
    # Build a dict of players indexed by steamid for later use
    playersdict = {player["steamid"]: player for player in playerslist}
    # Build a dict of games indexed by appid, with a list of owners identified by steamid
    appid_game_steamids_dict = {}
    for steamid, games in steamid_games_list:
        for game in games:
            appid = game["appid"]
            if appid in appid_game_steamids_dict:
                appid_game_steamids_dict[appid][1].append(steamid)
            else:
                appid_game_steamids_dict[appid] = (game, [steamid])
    # Build sorted list of games per number of owners
    game_ownercount_list = [
        (
            game,
            len(steamids),
            [steamid for steamid in steamids])
        for game, steamids in appid_game_steamids_dict.values()]
    game_ownercount_list.sort(reverse=True, key=lambda e: e[1])
    friends_with_games_count = len([
        steamid for steamid, games in steamid_games_list if len(games) != 0])
    # Send the results
    await ctx.send("List of the %d most owned games by %d friends of %s:" % (
        max_count, friends_with_games_count, player["personaname"]))
    for game, count, steamids in game_ownercount_list[:max_count]:
        embed = discord.Embed(
            title=game["name"], type="rich", url="https://store.steampowered.com/app/%s/" % game["appid"])
        embed.set_image(url="http://media.steampowered.com/steamcommunity/public/images/apps/%s/%s.jpg" % (
            game["appid"], game["img_logo_url"]))
        embed.add_field(name="Owned by", value="%d friends" % (count), inline=True)
        embed.set_footer(text="Owners: %s" % ", ".join(
            [playersdict[steamid]["personaname"] for steamid in steamids]))
        await ctx.send(embed=embed)


def get_games_recently_played_by_player(player):
    """Get the list of games recently played by a single player"""
    recent_games_response = call_steamapi(
        STEAM_APIKEY, "IPlayerService.GetRecentlyPlayedGames", steamid=player["steamid"], count=0)
    if "total_count" not in recent_games_response["response"] or recent_games_response["response"]["total_count"] <= 0:
        return player["steamid"], []
    return player["steamid"], recent_games_response["response"]["games"]


def get_games_recently_played_by_players(playerslist):
    """Build a a list of games recently played by players"""
    # Get a list of tuples (player, list of of games)
    pool = ThreadPool(10)
    return pool.map(get_games_recently_played_by_player, playerslist)


async def friends_recent(ctx, player, max_count, playerslist):
    """Display games most played recently among a list of players"""
        # Do the slow part in a separate thread: one synchronous call per player to the Steam API to be done
    with concurrent.futures.ThreadPoolExecutor() as pool:
        steamid_games_list = await bot.loop.run_in_executor(pool, functools.partial(
            get_games_recently_played_by_players, playerslist))
    # Build a dict of players indexed by steamid for later use
    playersdict = {player["steamid"]: player for player in playerslist}
    # Build a dict of games indexed by appid, with a list of owners identified by steamid
    appid_game_playtime_dict = {}
    for steamid, games in steamid_games_list:
        for game in games:
            appid = game["appid"]
            if appid in appid_game_playtime_dict:
                appid_game_playtime_dict[appid][1].append((game["playtime_2weeks"], steamid))
            else:
                appid_game_playtime_dict[appid] = (game, [(game["playtime_2weeks"], steamid)])
    # Build sorted list of games per playtime
    game_playtime_list = [
        (
            game,
            sum([playtime for playtime, _steamid in playtime_steamids]),
            len([steamid for _playtime, steamid in playtime_steamids]),
            [steamid for _playtime, steamid in playtime_steamids])
        for game, playtime_steamids in appid_game_playtime_dict.values()]
    game_playtime_list.sort(reverse=True, key=lambda e: e[1])
    friends_with_games_count = len([
        steamid for steamid, games in steamid_games_list if len(games) != 0])
    # Send the results
    await ctx.send("List of the %d most played games by %d friends of %s during the last 2 weeks:" % (
        max_count, friends_with_games_count, player["personaname"]))
    for game, playtime, count, steamids in game_playtime_list[:max_count]:
        embed = discord.Embed(
            title=game["name"], type="rich", url="https://store.steampowered.com/app/%s/" % game["appid"])
        embed.set_image(url="http://media.steampowered.com/steamcommunity/public/images/apps/%s/%s.jpg" % (
            game["appid"], game["img_logo_url"]))
        embed.add_field(name="Time played", value="%dh%dm" % divmod(playtime, 60), inline=True)
        embed.add_field(name="Played by", value="%d friends" % (count), inline=True)
        embed.set_footer(text="Players: %s" % ", ".join(
            [playersdict[steamid]["personaname"] for steamid in steamids]))
        await ctx.send(embed=embed)


@bot.command()
@has_vanity_name
async def friends(ctx, vanity_or_steamid=None, subcommand=None, max_count_str=10):
    """Get most owned or recently played games among friends"""
    if (inputs := await friends_check_input(ctx, vanity_or_steamid, subcommand, max_count_str)) is None:
        return
    steamid = inputs[0]
    max_count = inputs[1]
    # Get Summary for the player identified by steamid
    if (player := await get_player_summary(steamid)) is None:
        await ctx.send("Error fetching player summary")
        return
    # Get steamids of friends of the player
    friendlist_response = await call_steamapi_async(
        "ISteamUser.GetFriendList", steamid=steamid, relationship="friend")
    #print(friendlist_response)
    if "friendslist" not in friendlist_response or "friends" not in friendlist_response["friendslist"]:
        await ctx.send("Error fetching %s friendlist" % (steamid))
        return
    friends_steamids_list = [friend["steamid"] for friend in friendlist_response["friendslist"]["friends"]]
    await ctx.send("Player %s (%s) has %d friends" % (player["personaname"], steamid, len(friends_steamids_list)))

    # Get profile summaries of friends of the player
    friendslist = []
    steamapi_sclices_size = 50
    for i in range(0, len(friends_steamids_list), steamapi_sclices_size):
        # Beware the maximum length of steamids parameter (100)
        playersummaries_response = await call_steamapi_async(
            "ISteamUser.GetPlayerSummaries", steamids=",".join(friends_steamids_list[i:i+steamapi_sclices_size]))
        if "response" not in playersummaries_response or "players" not in playersummaries_response["response"]:
            await ctx.send("Error fetching friends summaries")
            return
        friendslist.extend(playersummaries_response["response"]["players"])

    # Simply list friends
    if subcommand == FRIENDS_LIST:
        await friends_list(ctx, player, max_count, friendslist)
    # List most owned games
    elif subcommand == FRIENDS_OWNED:
        await friends_owned(ctx, player, max_count, friendslist)
    # List recently played games
    elif subcommand == FRIENDS_RECENT:
        await friends_recent(ctx, player, max_count, friendslist)


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

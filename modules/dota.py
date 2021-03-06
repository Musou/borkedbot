import sys
sys.dont_write_bytecode = True

from HTMLParser import HTMLParser
import os, time, json, subprocess, shlex, requests, feedparser
import steamapi, twitchapi, settings, node


LOAD_ORDER = 35


enabled_channels = {ch:(settings.getdata('%s_common_name' % ch),settings.getdata('%s_mmr_enabled' % ch)) for ch in settings.getdata('dota_enabled_channels')}

rss_channels = {}

STEAM_TO_DOTA_CONSTANT = 76561197960265728

POSITION_COLORS = ['Blue', 'Teal', 'Purple', 'Yellow', 'Orange', 'Pink' , 'Gray', 'Light Blue', 'Green', 'Brown']


def dotaToSteam(dotaid):
    return long(dotaid) + STEAM_TO_DOTA_CONSTANT

def steamToDota(steamid):
    return long(steamid) - STEAM_TO_DOTA_CONSTANT


def update_channels():
    global enabled_channels
    # print "[Dota] Updating enabled channels"
    enabled_channels = {ch:(settings.getdata('%s_common_name' % ch),settings.getdata('%s_mmr_enabled' % ch)) for ch in settings.getdata('dota_enabled_channels')}
    # os.system('touch %s' % os.path.abspath(__file__))


def enable_channel(channel, dotaid, mmr=False):
    dotaid = steamToDota(determineSteamid(dotaid))
    en_chans = settings.getdata('dota_enabled_channels')

    settings.setdata('dota_enabled_channels', list(set(en_chans + [channel])))
    settings.trygetset('%s_common_name' % channel, channel)
    settings.setdata('%s_mmr_enabled' % channel, mmr)

    settings.setdata('%s' % channel, dotaToSteam(dotaid), domain='steamids')
    settings.setdata('%s_dota_id' % channel, dotaid)

    update_channels()


def disable_channel(channel, mmr=False):
    en_chans = settings.getdata('dota_enabled_channels')
    settings.setdata('dota_enabled_channels', list(set(en_chans) - set([channel])))
    settings.setdata('%s_mmr_enabled' % channel, not mmr)


def setup(bot):
    return

def alert(event):
    if event.channel in enabled_channels:
        if event.etype == 'msg': # Meh
            mes_count = settings.trygetset('%s_notable_message_count' % event.channel, 1)
            settings.setdata('%s_notable_message_count' % event.channel, mes_count + 1, announce=False)

            try:
                blurb(event.channel, event.bot)
            except Exception, e:
               print '[Dota-Error] Match blurb failure: %s' % e

        if event.etype == 'timer':
            try:
                rss_update = check_for_steam_dota_rss_update(event.channel)
                if rss_update:
                    print '[Dota] RSS update found: ' + rss_update
                    event.bot.botsay(rss_update)
            except Exception, e:
                print '[Dota-Error] RSS check failure: %s' % e

            try:
                nblurb = notablePlayerBlurb(event.channel)
                if nblurb:
                    event.bot.botsay(nblurb)
            except Exception, e:
                print '[Dota-Error] Notable player blurb failure: %s' % e


def blurb(channel, bot, override=False):
    t1 = time.time()
    r = latestBlurb(channel, override)

    if r is not None:
        t2 = time.time()
        print "[Dota] Blurb time: %4.4fms" % ((t2-t1)*1000)

        bot.botsay(r)

    return r is not None

def latestBlurb(channel, override=False):
    if checktimeout(channel) or override:
        dotaid = settings.getdata('%s_dota_id' % channel)
        if dotaid is None:
            print "[Dota] No ID on record for %s.  I should probably sort this out." % channel
            return


        # try:
            # latestmatch = steamapi.getlastdotamatch(dotaid)
        # except Exception as e:
            # print "[Dota] API error:", e
            # return
        try:
            matches = steamapi.GetMatchHistory(account_id=dotaid, matches_requested=25)['result']['matches']
        except:
            return

        settings.setdata('%s_last_match_fetch' % channel, time.time(), announce=False)

        latestmatch = matches[0]
        previousnewmatch = matches[1]
        previoussavedmatch = settings.trygetset('%s_last_match' % channel, latestmatch)

        if previoussavedmatch['match_id'] != latestmatch['match_id'] or override:
            if previoussavedmatch['match_id'] != previousnewmatch['match_id']:
                # Other matches have happened.

                matchlist = [m['match_id'] for m in matches]

                # TODO: Fix -1 issues for lastmatch
                # For some reason, a failed match (early abandon) was never saved as the lastest match
                try:
                    skippedmatches = matchlist.index(previoussavedmatch['match_id']) - 1
                except:
                    skippedmatches = 0
                print '[Dota] Skipped %s matches MAYBE PROBABLY I HOPE SO' % skippedmatches
            else:
                skippedmatches = 0

            update_channels()
            notable_check_timeout = settings.trygetset('%s_notable_check_timeout' % channel, 900.0)

            settings.setdata('%s_notable_last_check' % channel, time.time() - notable_check_timeout + 60.0, announce=False)
            settings.setdata('%s_notable_message_count' % channel, settings.trygetset('%s_notable_message_limit' % channel, 50), announce=False)

            print "[Dota] Match ID change found (%s:%s) (Lobby type %s)" % (previoussavedmatch['match_id'], latestmatch['match_id'], str(latestmatch['lobby_type']))
            return getLatestGameBlurb(channel, dotaid, latestmatch, skippedmatches=skippedmatches, getmmr = enabled_channels[channel][1] and str(latestmatch['lobby_type']) == '7')


def checktimeout(channel):
    twitchchecktimeout = settings.trygetset('twitch_online_check_timeout', 15)
    lastonlinecheck = settings.trygetset('twitch_online_last_check', time.time())

    try:
        is_streaming = twitchapi.is_streaming(channel)
    except Exception as e:
        print '[Dota] twitch api check error:',e
        return False

    if is_streaming:
        if time.time() - int(twitchchecktimeout) > float(lastonlinecheck):
            settings.setdata('twitch_online_last_check', time.time(), announce=False)
        else:
            return True
    else:
        return False

    laststreamcheck = settings.trygetset('%s_last_is_streaming_check' % channel, time.time())
    streamchecktimeout = settings.trygetset('%s_is_streaming_timeout' % channel, 30)

    if time.time() - int(streamchecktimeout) > float(laststreamcheck):
        getmatchtimeout = settings.trygetset('%s_get_online_match_timeout' % channel, 20)
        settings.setdata('%s_last_is_streaming_check' % channel, time.time(), announce=False)

    getmatchtimeout = settings.trygetset('%s_get_match_timeout' % channel, 30)
    lastmatchfetch = settings.trygetset('%s_last_match_fetch' % channel, time.time())

    return time.time() - int(getmatchtimeout) > float(lastmatchfetch)


def getLatestGameBlurb(channel, dotaid, latestmatch=None, skippedmatches=0, getmmr=False, notableplayers=True, splitlongnotable=True):
    if latestmatch is None:
        latestmatch = steamapi.getlastdotamatch(dotaid)

    settings.setdata('%s_last_match' % channel, latestmatch, announce=False)

    matchdata = steamapi.GetMatchDetails(latestmatch['match_id'])
    herodata = steamapi.GetHeroes()

    for p in matchdata['result']['players']:
        if str(p['account_id']) == str(dotaid):
            playerdata = p
            break

    notableplayerdata = None
    separate_notable_message = False

    if notableplayers:
        # print "notable player lookup requested"
        notable_players = settings.getdata('dota_notable_players')
        notable_players_found = []

        if dotaid in notable_players:
            notable_players.pop(dotaid)

        for p in matchdata['result']['players']:
            # print 'looking up %s' % p['account_id']
            if p['account_id'] in notable_players:
                # print '[Dota-Notable] Found notable player %s' % notable_players[p['account_id']]
                playerhero = str([h['localized_name'] for h in herodata['result']['heroes'] if str(h['id']) == str(p['hero_id'])][0]) # p['heroId'] ?

                if int(p['account_id']) != int(dotaid):
                    notable_players_found.append((notable_players[p['account_id']], playerhero))

        if notable_players_found:
            separate_notable_message = len(notable_players_found) > 3

            notableplayerdata = "Notable players: %s" % ', '.join(['%s - %s' % (p,h) for p,h in notable_players_found])
            print "[Dota-Notable] notable player data: " + notableplayerdata
        else:
            print '[Dota-Notable] No notable players found'

    try:
        d_hero = [h['localized_name'] for h in herodata['result']['heroes'] if str(h['id']) == str(playerdata['hero_id'])][0]
    except:
        d_hero = 'Unknown Hero'

    d_team = 'Radiant' if int(playerdata['player_slot']) < 128 else 'Dire'
    d_level = playerdata['level']

    d_kills = playerdata['kills']
    d_deaths = playerdata['deaths']
    d_assists = playerdata['assists']

    d_lasthits = playerdata['last_hits']
    d_denies = playerdata['denies']

    d_gpm = playerdata['gold_per_min']
    d_xpm = playerdata['xp_per_min']

    d_victory = 'Victory' if not (matchdata['result']['radiant_win'] ^ (d_team == 'Radiant')) else 'Defeat'


    print "[Dota] Skipped %s matches" % skippedmatches

    if skippedmatches == -1:
        matchskipstr = '(Previous match) '
    elif skippedmatches < -1:
        matchskipstr = '(%s games ago) ' % skippedmatches * -1
    elif skippedmatches > 1:
        matchskipstr = '(%s skipped) ' % skippedmatches
    else:
        matchskipstr = ''

    matchoutput = "%s%s has %s a game.  http://www.dotabuff.com/matches/%s" % (
        matchskipstr,
        enabled_channels[channel][0],
        'won' if d_victory == 'Victory' else 'lost',
        latestmatch['match_id'])

    extramatchdata = "Level {} {} {} - KDA: {}/{}/{} - CS: {}/{} - GPM: {} - XPM: {}".format(
        d_level, d_team, d_hero, d_kills, d_deaths, d_assists, d_lasthits, d_denies, d_gpm, d_xpm)


    finaloutput = matchoutput + ' -- ' + extramatchdata + (' -- ' + getmatchMMRstring(channel, dotaid) if getmmr else '') + (' -- ' + notableplayerdata if notableplayerdata else '')

    if splitlongnotable:
        pass

    return finaloutput


def getmatchMMRstring(channel, dotaid):
    outputstring = "Updated MMR: Solo: %s | Party: %s "

    print "[Dota-MMR] Updating mmr"

    with open('/var/www/twitch/%s/data' % channel, 'r') as d:
        olddotadata = json.loads(d.readline())

    wentok = updateMMR(channel)
    if not wentok:
        print "[Dota-MMR] SOMETHING MAY HAVE GONE HORRIBLY WRONG GETTING MMR"

    with open('/var/www/twitch/%s/data' % channel, 'r') as d:
        dotadata = json.loads(d.readline())

    old_mmr_s = str(olddotadata['gameAccountClient']['soloCompetitiveRank'])
    old_mmr_p = str(olddotadata['gameAccountClient']['competitiveRank'])

    new_mmr_s = str(dotadata['gameAccountClient']['soloCompetitiveRank'])
    new_mmr_p = str(dotadata['gameAccountClient']['competitiveRank'])

    mmr_s_change = str(int(new_mmr_s) - int(old_mmr_s))
    mmr_p_change = str(int(new_mmr_p) - int(old_mmr_p))

    if int(mmr_s_change) >= 0: mmr_s_change = '+' + mmr_s_change
    if int(mmr_p_change) >= 0: mmr_p_change = '+' + mmr_p_change

    return outputstring % ('%s (%s)' % (new_mmr_s, mmr_s_change), '%s (%s)' % (new_mmr_p, mmr_p_change))


def getUserDotaData(channel, datapath = '/var/www/twitch/%s/data'):
    with open(datapath % channel, 'r') as d:
        return json.loads(d.readline())


def updateMMR(channel):
    try:
        dotaid = str(settings.getdata('%s_dota_id' % channel))
    except:
        raise TypeError("No id on record")

    return node.updateMMR(channel, dotaid)


def determineSteamid(steamthing):
    # print '[Dota] Determining steamid for input: %s' % steamthing

    steamthing = str(steamthing)

    if steamthing.startswith('STEAM_'):
        sx,sy,sz = steamthing.split('_')[1].split(':')
        maybesteamid = (int(sz)*2+int(sy)) + STEAM_TO_DOTA_CONSTANT

    elif 'steamcommunity.com/profiles/' in steamthing:
        maybesteamid = [x for x in steamthing.split('/') if x][-1] # oh I hope this works

    elif 'steamcommunity.com/id/' in steamthing:
        try:
            result = steamapi.ResolveVanityURL([x for x in steamthing.split('/') if x][-1])['response']
        except:
            return False

        if result['success'] == 1:
            maybesteamid = result['steamid']
        else:
            maybesteamid = None
    else:
        import re
        match = re.match('^\d*$', steamthing)
        if match:
            if long(match.string) < STEAM_TO_DOTA_CONSTANT:
                maybesteamid  = long(match.string) + STEAM_TO_DOTA_CONSTANT
            else:
                maybesteamid = match.string
        else:
            try:
                result = steamapi.ResolveVanityURL(steamthing)['response']
            except:
                return False

            if result['success'] == 1:
                maybesteamid = result['steamid']
            else:
                maybesteamid = None

    print '[Dota] Determined that steamid for %s is %s' % (steamthing, maybesteamid)
    return maybesteamid


def getSourceTVLiveGameForPlayer(targetdotaid):
    totalgames = node.get_source_tv_games()['numTotalGames']

    for pagenum in range(0, int(round(float(totalgames)/6))):
        games = node.get_source_tv_games(pagenum)['games']

        for game in games:
            try:
                game['goodPlayers']
                game['badPlayers']
            except Exception, e:
                print "MALFORMED GAME DATA, DO SOMETHING ABOUT IT (Radiant: %s, Dire: %s)" % (len(game.get('goodPlayers', [])), len(game.get('badPlayers', [])))
                continue

            players = []
            players.extend(game['goodPlayers'])
            players.extend(game['badPlayers'])
            notable_players_found = []
            target_found = False

            for player in players:
                if steamToDota(player['steamId']) == long(targetdotaid):
                    return game

def dec2ip(addr):
    binnum = '{0:b}'.format(int(addr)).zfill(32)
    pall = [binnum[i:i+8] for i in xrange(0, len(binnum), 8)]
    return '.'.join([str(int(p,2)) for p in pall])

def get_console_connect_code(dotaid):
    ddata = getSourceTVLiveGameForPlayer(dotaid)
    return 'connect_hltv ' + dec2ip(ddata['sourceTvPublicAddr']) + ':' + str(ddata['sourceTvPort'])

    #TODO: Figure out how the console command and "Watch game" (NotifyClientSignon 0/1/2) are different


def searchForNotablePlayers(targetdotaid, pages=4):
    # Needs check for if in a game (maybe need a status indicator for richPresence)
    t0 = time.time()
    herodata = steamapi.GetHeroes()
    notable_players = settings.getdata('dota_notable_players')

    for pagenum in range(0, pages):
        # print 'searching page %s, T+%4.4fms' % (pagenum, (time.time()-t0)*1000)
        games = node.get_source_tv_games(pagenum)['games']
        # print 'received game page %s, T+%4.4fms' % (pagenum, (time.time()-t0)*1000)

        for game in games:
            try:
                game['goodPlayers']
                game['badPlayers']
            except Exception, e:
                print "MALFORMED GAME DATA, DO SOMETHING ABOUT IT (Radiant: %s, Dire: %s)" % (len(game.get('goodPlayers', [])), len(game.get('badPlayers', [])))
                continue

            players = []
            players.extend(game['goodPlayers'])
            players.extend(game['badPlayers'])
            notable_players_found = []
            target_found = False

            for player in players:
                if steamToDota(player['steamId']) in notable_players:
                    print '[Dota-Notable] %s (%s)' % (player['name'], notable_players[steamToDota(player['steamId'])])

                    try:
                        playerhero = str([h['localized_name'] for h in herodata['result']['heroes'] if str(h['id']) == str(player['heroId'])][0])
                    except:
                        # try:
                            # print 'found notable player picking hero %s, position ' % notable_players[steamToDota(player['steamId'])],
                            # print players.index(player)
                            # print 'I think their color is %s' % POSITION_COLORS[players.index(player)]
                        # except Exception, e:
                            # print 'you borked something idiot', e

                        playerhero = POSITION_COLORS[players.index(player)]

                    if long(steamToDota(player['steamId'])) != long(targetdotaid):
                        notable_players_found.append((notable_players[steamToDota(player['steamId'])], playerhero))
                    else:
                        print '[Dota-Notable] Discounting target player'

                if steamToDota(player['steamId']) == long(targetdotaid):
                    print '[Dota-Notable] found target player,',
                    target_found = True

            #TODO: ADD THE OTHER DATA IN HERE SOMEWHERE

            if target_found:
                if notable_players_found:
                    print 'managed to find: %s' % notable_players_found
                else:
                    print 'no notable players.'

                return notable_players_found
            # print 'searched game %s, T+%4.4fms' % (games.index(game), (time.time()-t0)*1000)

        print '[Dota-Notable] searched game page %s, T+%4.4fms' % (pagenum, (time.time()-t0)*1000)


def getNotableCheckReady(channel):
    lastcheck = settings.trygetset('%s_notable_last_check' % channel, time.time())
    message_limit = settings.trygetset('%s_notable_message_limit' % channel, 50)
    notable_check_timeout = settings.trygetset('%s_notable_check_timeout' % channel, 900.0)

    if time.time() - lastcheck > notable_check_timeout:
        mes_count = settings.trygetset('%s_notable_message_count' % channel, 1)
        if mes_count <= message_limit:
            return False
        settings.setdata('%s_notable_last_check' % channel, time.time(), announce=False)
        return True
    else:
        # print notable_check_timeout - (time.time() - lastcheck)
        return False

# TODO:
#    Stop further searches if no players are found
#    Store results for use in end game blurb
#    Fine tune usage frequency
def notablePlayerBlurb(channel, pages=33):
    userstatus = node.get_user_status(dotaToSteam(settings.getdata('%s_dota_id' % channel)))
    if userstatus:
        # print 'Dota status for %s: %s' % (channel, userstatus)

        if userstatus.replace('#','') in ["DOTA_RP_HERO_SELECTION", "DOTA_RP_PRE_GAME", "DOTA_RP_GAME_IN_PROGRESS", "DOTA_RP_PLAYING_AS"]:
            if getNotableCheckReady(channel):
                if twitchapi.is_streaming(channel):
                    print "[Dota-Notable] Doing search for notable players"
                    players = searchForNotablePlayers(settings.getdata('%s_dota_id' % channel), pages)
                    settings.setdata('%s_notable_message_count' % channel, 0, announce=False)

                    if players:
                        return "Notable players in this game: %s" % ', '.join(['%s (%s)' % (p,h) for p,h in players])
        else:
            notable_check_timeout = settings.trygetset('%s_notable_check_timeout' % channel, 900.0)
            settings.setdata('%s_notable_last_check' % channel, time.time() - notable_check_timeout + 60.0, announce=False)


def update_verified_notable_players():
    class DotabuffParser(HTMLParser):
        table_active = False
        img_section_active = False
        player_datas = list()

        def handle_starttag(self, tag, attrs):
            if tag == 'tbody':
                self.table_active = True
            if tag == 'img':
                self.img_section_active = True
            if not self.table_active: return
            if not self.img_section_active: return

            fulldatas = dict((x,y) for x,y in attrs)
            self.player_datas.append((int(fulldatas['data-tooltip-url'].split('/')[2]), fulldatas['title']))

        def handle_endtag(self, tag):
            if tag == 'tbody':
                self.table_active = False
            if tag == 'img':
                self.img_section_active = False
            if not self.table_active: return
            if not self.img_section_active: return

    parser = DotabuffParser()

    r = requests.get('http://www.dotabuff.com/players', headers = {'User-agent': 'Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:34.0) Gecko/20100101 Firefox/34.0.1'})
    htmldata = unicode(r.text).encode('utf8')
    parser.feed(htmldata)

    old_players = settings.getdata('dota_notable_players')
    updated_players = dict(old_players.items() + parser.player_datas)

    settings.setdata('dota_notable_players', updated_players, announce=False)

    tn = 0
    for p in dict(parser.player_datas):
        o = old_players.get(p, 'none')
        n = dict(parser.player_datas)[p]
        if o != n:
            print '[Dota-Notable] Updated player: %s -> %s' % (o, n)
            tn += 1

    return tn

def check_for_steam_dota_rss_update(channel, setkey=True):
    last_rss_check = settings.trygetset('%s_last_dota_rss_check' % channel, time.time())

    if time.time() - last_rss_check < 30.0:
        return

    settings.setdata('%s_last_dota_rss_check' % channel, time.time(), announce=False)


    rs = node.get_steam_rss()
    last_feed_url = settings.trygetset('%s_dota_last_steam_rss_update_url' % channel, '0')

    for item in rs:
        if not item: continue
        if item['author'] == 'Valve' and 'Dota 2 Update' in item['title']:
            if item['guid'] != last_feed_url:
                # print '[Dota-RSS] Found steam blog update'
                if last_feed_url == 'derp': last_feed_url = '0'

                try:
                    bpn_old = int([x for x in last_feed_url.split('/') if x][-1])
                    bpn_new = int([x for x in item['guid'].split('/') if x][-1])

                    if bpn_old >= bpn_new:
                        break
                except Exception as e:
                    print '[Dota-RSS] Error checking steam rss:', e
                    # print "Ok what the fuck is up with the steam rss"
                    break

                settings.setdata('%s_dota_last_steam_rss_update_url' % channel, str(item['guid']))

                return str("Steam News Feed: %s - %s" % (item['title'], item['guid']))
            else:
                break


    rs = node.get_dota_rss()
    last_feed_url = settings.trygetset('%s_dota_last_dota2_rss_update_url' % channel, '0')

    for item in rs:
        if not item: continue
        if item['guid'] != last_feed_url:
            if last_feed_url == 'derp': last_feed_url = '0'

            try:
                bpn_old = int(last_feed_url.split('=')[-1])
                bpn_new = int(item['guid'].split('=')[-1])

                if bpn_old >= bpn_new:
                    break
            except Exception as e:
                print '[Dota-RSS] Error checking dota rss:', e
                # print "Ok what the fuck is up with the dota rss"
                break

            settings.setdata('%s_dota_last_dota2_rss_update_url' % channel, str(item['guid']))

            # print '[Dota-RSS] Found dota blog update'
            return str("Dota 2 Blog Post: %s - %s" % (item['title'], item['link']))
        else:
            break

def get_latest_steam_dota_rss_update():
    rs = node.get_steam_rss()

    for item in rs:
        if item['author'] == 'Valve' and 'Dota 2 Update' in item['title']:
            return str("Steam RSS News Feed: %s - %s" % (item['title'], item['guid']))



class Lobby(object):

    GAMEMODE_All_Pick          = 1
    GAMEMODE_Captains_Mode     = 2
    GAMEMODE_Random_Draft      = 3
    GAMEMODE_Single_Draft      = 4
    GAMEMODE_All_Random        = 5
    GAMEMODE_Reverse_Captains  = 8
    GAMEMODE_Mid_Only          = 11
    GAMEMODE_Least_Played      = 12
    GAMEMODE_Limited_Heroes    = 13
    GAMEMODE_Ability_Draft     = 18
    GAMEMODE_ARDM              = 20
    GAMEMODE_1v1mid            = 21
    GAMEMODE_All_Draft         = 22

    GAMEMODES = {
        'ap': 1, 'cm':2, 'rd':3, 'sd':4, 'ar':5, 'rcm':8, 'mo': 11,
        'lp':12, 'lh':13, 'ad': 18, 'ardm':20, '1v1':21, 'rap':22 }

    SERVER_Unspecified         = 0
    SERVER_USWest              = 1
    SERVER_USEast              = 2
    SERVER_Europe              = 3
    SERVER_Korea               = 4
    SERVER_Singapore           = 5
    SERVER_Australia           = 7
    SERVER_Stockholm           = 8
    SERVER_Austria             = 9
    SERVER_Brazil              = 10
    SERVER_Southafrica         = 11
    SERVER_PerfectworldTelecom = 12
    SERVER_PerfectworldUnicom  = 13

    SERVERS = {
        'auto':0, 'uswest':1, 'useast':2, 'europe' : 3,
        'korea' : 4, 'singapore' : 5, 'australia' : 7,
        'stockholm' : 8, 'austria' : 9, 'brazil' : 10,
        'southafrica' : 11, 'perfectworldtelecom' : 12,
        'perfectworldunicom' : 13 }

    def __init__(self, channel, name=None, password=None, mode=None, region=None):
        import node

        self.channel = channel
        self.name = name
        self.password = password
        self.mode = mode
        self.region = region

        self.lobby_id = None
        self.created = False
        self.started = False

    def create(self):
        lobbyid = node.create_lobby(self.name, self.mode, self.password, self.region)

        if lobbyid is None:
            return False

        self.lobby_id = lobbyid
        self.created = True

    def leave(self):
        node.leave_lobby()

    def remake(self, name=None, password=None, mode=None, region=None):
        self.name = name or self.name
        self.password = password or self.password
        self.mode = mode or self.mode
        self.region = region or self.region

        node.leave_lobby()
        self.create()

    def start(self):
        node.start_lobby()
        self.started = True

    def shuffle(self):
        node.shuffle_lobby()

    def flip(self):
        node.flip_lobby()

    def kick_from(self, steamid): # change to accept other inputs (chat names)
        node.kick_lobby(steamid)

    def config(self): # rjackson pls
        return

import sys
sys.dont_write_bytecode = True

import os, dill, redis

LOAD_ORDER = 50

redisdb = redis.StrictRedis(db=3)

defaultdomain = 'settings-global'


def getdata(key, domain=defaultdomain, coerceto=None):
    result = dill.loads(redisdb.hget(domain, key))

    if coerceto:
        return coerceto(result)
    else:
        return result


def setdata(key, value, domain=defaultdomain, announce=True):
    oldr = redisdb.hget(domain, key)

    if oldr:
        oldresult = dill.loads(oldr)
    else:
        oldresult = oldr

    isnew = redisdb.hset(domain, key, dill.dumps(value))

    if isnew and announce:
        print "[Settings] Key added%s: %s (%s)" % ('' if domain == defaultdomain else ' (in %s)' % domain, key, value)
    elif announce:
        print "[Settings] Key %s changed%s: %s -> %s" % ( key, '' if domain == defaultdomain else ' (in %s)' % domain, oldresult, value)


def trygetset(key, value, domain=defaultdomain, coerceto=None, announce=True):
    if not redisdb.hexists(domain, key):
        print "[Settings] Key added: %s (%s)" % (key, value)
        setdata(key, value, domain, announce)

    return getdata(key, domain, coerceto)


def deldata(key, domain=defaultdomain, announce=True):
    if announce:
        print "[Settings] Key deleted: %s" % key
    redisdb.hdel(domain, key)

def delete_all_channel_keys(channel, domain=defaultdomain, announce=True, backup=True):
    if announce:
        print '[Settings] Deleting all keys for %s' % channel

    for k in dumpkeys(domain):
        if k.startswith(channel):
            olddata = getdata(k, domain)
            deldata(k, domain)
            setdata(k, olddata, '%s_backup' % channel, False)


def exists(key, domain=defaultdomain):
    return redisdb.hexists(domain, key)

def numkeys(domain=defaultdomain):
    return redisdb.hlen(domain)

def dumpkeys(domain=defaultdomain):
    return {k:dill.loads(v) for k,v in redisdb.hgetall(domain).items()}

def setup(bot):
    return

def alert(event):
    return

import os
import json
from configUpdate import configUpdate


class Config(dict):
    def __init__(self, *args, **kwargs):
        dict.__init__(self, *args, **kwargs)
        # Load defaults:
        self['port'] = 8080
        self['memcachedServers'] = ["127.0.0.1:11211"]
        self['DiskCacheServer'] = "127.0.0.1:8888"
        self['log'] = {
            'path': "SymServer.log",
            'level': 30,
            'maxFiles': 5,
            'maxFileSizeMB': 50
        }

    def loadFile(self, path):
        with open(path, "r") as fp:
            config = fp.read()
        self.loadJSON(config)

    def loadJSON(self, JSON):
        config = json.loads(JSON)
        config = config['SymServer']
        configUpdate(self, config)
        self.sanitize()

    def loadArgs(self, args):
        if args.config is not None:
            self.loadFile(args.config)
        if args.configJSON is not None:
            self.loadJSON(args.configJSON)
        if args.port is not None:
            self['port'] = args.port
        if args.memcachedServer is not None:
            if len(args.memcachedServer) == 1 and args.memcachedServer[0].lower() == "none":
                self['memcachedServers'] = []
            else:
                self['memcachedServers'] = args.memcachedServer
        if args.diskCacheServer is not None:
            self['DiskCacheServer'] = args.diskCacheServer
        if args.logPath is not None:
            self['log']['path'] = args.logPath
        if args.logLevel is not None:
            self['log']['level'] = args.logLevel
        if args.logFiles is not None:
            self['log']['maxFiles'] = args.logFiles
        if args.logFileSize is not None:
            self['log']['maxFileSizeMB'] = args.logFileSize
        self.sanitize()

    def sanitize(self):
        self['log']['path'] = os.path.realpath(self['log']['path'])
        if (not self['DiskCacheServer'].startswith(("http://", "https://"))):
            self['DiskCacheServer'] = "http://" + self['DiskCacheServer']

config = Config()

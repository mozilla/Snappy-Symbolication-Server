import os
import json
from configUpdate import configUpdate


class Config(dict):
    def __init__(self, *args, **kwargs):
        dict.__init__(self, *args, **kwargs)
        # Load defaults:
        self['cachePath'] = os.path.realpath("./DiskCacheData")
        self['localSymbolDirs'] = []
        self['maxSizeMB'] = 200
        self['port'] = 8888
        self['symbolURLs'] = [
            "https://s3-us-west-2.amazonaws.com/org.mozilla.crash-stats.symbols-public/v1/"
        ]
        self['log'] = {
            'path': "DiskCache.log",
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
        config = config['DiskCache']
        configUpdate(self, config)
        self.sanitize()

    def loadArgs(self, args):
        if args.config is not None:
            self.loadFile(args.config)
        if args.configJSON is not None:
            self.loadJSON(args.configJSON)
        if args.cachePath is not None:
            self['cachePath'] = args.cachePath
        if args.localSymbols is not None:
            self['localSymbolDirs'] = args.localSymbols
        if args.maxSize is not None:
            self['maxSizeMB'] = args.maxSize
        if args.port is not None:
            self['port'] = args.port
        if args.symbolURL is not None:
            self['symbolURLs'] = args.symbolURL
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
        self['cachePath'] = os.path.realpath(self['cachePath'])
        for index, symbolURL in enumerate(self['symbolURLs']):
            if not symbolURL.endswith('/'):
                self['symbolURLs'][index] = symbolURL + "/"

config = Config()

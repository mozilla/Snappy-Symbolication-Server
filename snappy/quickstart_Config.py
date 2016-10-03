import json
from configUpdate import configUpdate

class Config(dict):
    def __init__(self, *args, **kwargs):
        dict.__init__(self, *args, **kwargs)
        # Load defaults:
        self['verbose'] = False
        self['Docker'] = {
            "enable": False,
            "publish": {
                "memcached": False,
                "DiskCache": False,
                "SymServer": True
            },
            "apiSocket": "unix:///var/run/docker.sock"
        }
        self['memcached'] = {
            "start": True,
            "restart": False,
            "binary": "memcached",
            "port": 11211,
            "listenAddress": "0.0.0.0",
            "maxMemoryMB": 64
        }
        self['DiskCache'] = {
            "start": True,
            "restart": True
        }
        self['SymServer'] = {
            "start": True,
            "restart": False
        }

    def loadFile(self, path):
        with open(path, "r") as fp:
            config = fp.read()
        self.loadJSON(config)
        try:
            del self['configJSON']
        except KeyError:
            pass
        self['configPath'] = path

    def loadJSON(self, JSON):
        config = json.loads(JSON)
        config = config['quickstart']
        configUpdate(self, config)
        self.sanitize()
        try:
            del self['configPath']
        except KeyError:
            pass
        self['configJSON'] = JSON

    def sanitize(self):
        # Placeholder. Currently no sanitizing needed.
        pass

config = Config()

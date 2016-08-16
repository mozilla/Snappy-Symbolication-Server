import os
import json

class Config(dict):
  def __init__(self, *args, **kwargs):
    dict.__init__(self, *args, **kwargs)
    # Load defaults:
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
    if 'memcached' in config:
      self['memcached'].update(config['memcached'])
    if 'DiskCache' in config:
      self['DiskCache'].update(config['DiskCache'])
    if 'SymServer' in config:
      self['SymServer'].update(config['SymServer'])
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

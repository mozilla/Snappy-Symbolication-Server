#!/usr/bin/env python
import sys
import os
import argparse
import subprocess
import multiprocessing
import urllib2
import contextlib
import time
import uuid
try:
  import psutil
  import memcache
except ImportError:
  pass # We will address this later in |missingDependencies|

from snappy.quickstart_Config import config
import snappy.DiskCache_Config as DiskCache
import snappy.SymServer_Config as SymServer


START_SERVER_TIMEOUT_SEC = 5
POLL_TIME_SEC = 0.2

SRC_DIR = os.path.dirname(os.path.realpath(__file__))
BIN_DIR = os.path.join(SRC_DIR, "snappy")
DISKCACHE_PATH = os.path.join(BIN_DIR, "DiskCache.py")
SYMSERVER_PATH = os.path.join(BIN_DIR, "SymServer.py")
PID_DIR = os.path.join(SRC_DIR, "pids")
MEMCACHED_PIDFILE = os.path.join(PID_DIR, "memcached.pid")
DISKCACHE_PIDFILE = os.path.join(PID_DIR, "DiskCache.pid")
SYMSERVER_PIDFILE = os.path.join(PID_DIR, "SymServer.pid")

def main():
  missing = missingDependencies()
  if missing:
    print "Error: Missing dependencies detected!"
    print "You can install missing dependencies by running:"
    print "python -m pip install -r requirements.txt"
    return -1

  parser = argparse.ArgumentParser(
    description = "Start servers needed for symbolication")
  group = parser.add_mutually_exclusive_group(required = True)
  group.add_argument('--config', '-c', metavar = "PATH", help = "Path to the "
    "config JSON file.")
  group.add_argument('--configJSON', metavar = "JSON", help = "Literal JSON to "
    "load configuration from rather than a configuration file.")
  group.add_argument('--stop', action = "store_true", help = "If specified, "
    "this script will stop all servers rather than starting them. Note that "
    "this will not necessarily work if quickstart was not used to start the "
    "servers.")
  args = parser.parse_args()
  if quickstart(args.config, args.configJSON, bool(args.stop)):
    return 0
  else:
    return -1

def quickstart(configPath = None, configJSON = None, stop = False):
  """ Only one argument should be specified.
  """
  if not os.path.exists(PID_DIR):
    os.makedirs(PID_DIR)

  if configPath:
    config.loadFile(configPath)
  elif configJSON:
    config.loadJSON(configJSON)

  if not stopServers(config, stopAll = stop):
    return False

  if not stop:
    if not startServers(config):
      return False
    if not serversResponding(config):
      return False

  return True

def missingDependencies():
  missing = []
  try:
    from concurrent.futures import Future
    assert Future
  except ImportError:
    missing.append("futures")
  try:
    import tornado.ioloop
    import tornado.web
    assert tornado.ioloop
    assert tornado.web
  except ImportError:
    missing.append("tornado")
  try:
    import memcache
    assert memcache
  except ImportError:
    missing.append("python-memcached")
  try:
    import psutil
    assert psutil
  except ImportError:
    missing.append("psutil")

  return missing

def stopServers(config, stopAll):
  pidfiles = []
  if stopAll or not config['SymServer']['start'] or config['SymServer']['restart']:
    pidfiles.append(SYMSERVER_PIDFILE)
  if stopAll or not config['DiskCache']['start'] or config['DiskCache']['restart']:
    pidfiles.append(DISKCACHE_PIDFILE)
  if stopAll or not config['memcached']['start'] or config['memcached']['restart']:
    pidfiles.append(MEMCACHED_PIDFILE)

  processes = []
  for pidfile in pidfiles:
    process = getProcess(pidfile)
    if process:
      processes.append(process)

  if not processes:
    print "No servers to stop"
    return True

  print "Stopping servers..."
  for process in processes:
    process.terminate()
  gone, alive = psutil.wait_procs(processes, timeout = 5)
  if alive:
    print "Some servers still have not stopped. Attempting to force..."
    for process in alive:
      process.kill()
    gone, alive = psutil.wait_procs(alive, timeout = 5)
    if alive:
      print "Unable to stop all servers"
      return False

  print "Servers stopped"
  return True

def startServers(config):
  # This one is easy because it already has an option to start as a daemon
  if config['memcached']['start'] and not memcachedRunning():
    command = [
      str(config['memcached']['binary']),
      "-d",
      "-U", "0",
      "-l", str(config['memcached']["listenAddress"]),
      "-m", str(config['memcached']["maxMemoryMB"]),
      "-p", str(config['memcached']["port"]),
      "-P", str(MEMCACHED_PIDFILE)
    ]
    print "Starting memcached with command: {}".format(command)
    with open(os.devnull, 'w') as devnull:
      subprocess.call(command, stdout = devnull, stderr = devnull)

  # Get the options to specify the configuration to the SymServer and DiskCache
  configOptions = []
  if 'configPath' in config:
    configOptions.append("-c")
    configOptions.append(str(config['configPath']))
  elif 'configJSON' in config:
    configOptions.append("--configJSON")
    configOptions.append(str(config['configJSON']))

  # The remaining servers require some weirdness in order to start them as
  # daemons
  # Mechanism was inspired by http://stackoverflow.com/a/33804441/4103025
  if config['DiskCache']['start'] and not diskCacheRunning():
    command = [
      "python",
      str(DISKCACHE_PATH),
      "--pidfile", str(DISKCACHE_PIDFILE)
    ]
    command.extend(configOptions)
    print "Starting DiskCache with command: {}".format(command)
    runDaemon(command)

  if config['SymServer']['start'] and not symServerRunning():
    command = [
      "python",
      str(SYMSERVER_PATH),
      "--pidfile", str(SYMSERVER_PIDFILE)
    ]
    command.extend(configOptions)
    print "Starting SymServer with command: {}".format(command)
    runDaemon(command)
  return True

def runDaemon(command):
  p = multiprocessing.Process(target = startProcess, args = (command,))
  p.start()
  p.join()

def startProcess(command):
  with open(os.devnull, 'w') as devnull:
    subprocess.Popen(command, stdout = devnull, stderr = devnull)

def memcachedRunning():
  return isRunning(MEMCACHED_PIDFILE)

def diskCacheRunning():
  return isRunning(DISKCACHE_PIDFILE)

def symServerRunning():
  return isRunning(SYMSERVER_PIDFILE)

def isRunning(pidfile):
  return (getProcess(pidfile) != None)

def getProcess(pidfile):
  try:
    with open(pidfile, 'r') as fp:
      pid = int(fp.read().strip())
    try:
      process = psutil.Process(pid)
      return process
    except psutil.NoSuchProcess:
      return None
  except IOError:
    # Couldn't read file. Likely doesn't exist, meaning process has not started
    return None
  return None

def serversResponding(config):
  timeoutEnd = time.time() + START_SERVER_TIMEOUT_SEC
  if config['DiskCache']['start']:
    while time.time() < timeoutEnd:
      if diskCacheRunning():
        break;
      time.sleep(POLL_TIME_SEC)
    else:
      print "Timeout exceeded waiting for DiskCache to start"
      return False

    # The config may not have a value for |port|. By loading the config the same
    # way that DiskCache loads it, we guarantee that we have the same value
    # that it has.
    if 'configPath' in config:
      DiskCache.config.loadFile(config['configPath'])
    elif 'configJSON' in config:
      DiskCache.config.loadJSON(config['configJSON'])

    while time.time() < timeoutEnd:
      response = sendGetRequest(DiskCache.config['port'])
      if response:
        break
      time.sleep(POLL_TIME_SEC)
    else:
      print "Timeout exceeded waiting for DiskCache to respond"
      return False

  if config['SymServer']['start']:
    while time.time() < timeoutEnd:
      if symServerRunning():
        break;
      time.sleep(POLL_TIME_SEC)
    else:
      print "Timeout exceeded waiting for SymServer to start"
      return False

    # Make sure we have a port value to contact SymServer on.
    if 'configPath' in config:
      SymServer.config.loadFile(config['configPath'])
    elif 'configJSON' in config:
      SymServer.config.loadJSON(config['configJSON'])

    while time.time() < timeoutEnd:
      response = sendGetRequest(SymServer.config['port'])
      if response:
        break
      time.sleep(POLL_TIME_SEC)
    else:
      print "Timeout exceeded waiting for SymServer to respond"
      return False

  if config['memcached']['start']:
    while time.time() < timeoutEnd:
      if memcachedRunning():
        break;
      time.sleep(POLL_TIME_SEC)
    else:
      print "Timeout exceeded waiting for memcached to start"
      return False

    m = memcache.Client(['127.0.0.1:{}'.format(config['memcached']['port'])])
    arbitraryKey = str(uuid.uuid4())
    arbitraryValue = arbitraryKey
    while time.time() < timeoutEnd:
      success = m.set(arbitraryKey, arbitraryValue)
      if success:
        break
      time.sleep(POLL_TIME_SEC)
    else:
      print "Timeout exceeded waiting for memcached to respond"
      return False
    m.delete(arbitraryKey)
  return True

def sendGetRequest(port):
  try:
    request = urllib2.Request("http://127.0.0.1:{}".format(port))
    with contextlib.closing(urllib2.urlopen(request)) as response:
      return {'code': response.getcode(), 'data': response.read()}
  except urllib2.HTTPError as err:
    return {'code': err.code, 'data': None}
  except urllib2.URLError:
    return None

if __name__ == '__main__':
  multiprocessing.freeze_support()
  sys.exit(main())

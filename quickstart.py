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
import json
try:
  import psutil
  import memcache
  import docker
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
DOCKER_CACHE_FILE = os.path.join(SRC_DIR, ".docker-cache")
DOCKER_IMAGE_NAME = "snappy"
DOCKER_CONTAINER_NAME = "snappy"

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
  parser.add_argument('--stop', action = "store_true", help = "If specified, "
    "this script will stop all servers rather than starting them. Note that "
    "this will not necessarily work if quickstart was not used to start the "
    "servers.")
  parser.add_argument('--foreground', '-F', action = "store_true",
    help = "Runs in the foreground rather than as a daemon.")
  parser.add_argument('--dockerRebuild', '-R', action = "store_true",
    help = "Forces a rebuild of the docker image.")
  args = parser.parse_args()
  if quickstart(args.config, args.configJSON, bool(args.stop), args.foreground,
                args.dockerRebuild):
    return 0
  else:
    return -1

def quickstart(configPath = None, configJSON = None, stop = False,
  foreground = False, dockerRebuild = False):
  """ Of the first two arguments, configPath, configJSON, exactly one should be
  specified.
  """
  if not os.path.exists(PID_DIR):
    os.makedirs(PID_DIR)

  if configPath:
    config.loadFile(configPath)
  elif configJSON:
    config.loadJSON(configJSON)

  if config["Docker"]["enable"]:
    if not stopDocker(config, forceStop = stop or dockerRebuild):
      return False
    if not stop:
      if not startDocker(config, foreground, dockerRebuild):
        return False
  else:
    if not stopServers(config, stopAll = stop):
      return False
    if not stop:
      if not startServers(config, foreground):
        return False
      if not foreground:
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
  try:
    import docker
    assert docker
  except ImportError:
    missing.append("docker-py")

  return missing

def stopServers(config, stopAll = False):
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

def startServers(config, foreground = False):
  startSymServer = config['SymServer']['start'] and not symServerRunning()
  foregroundSymServer = foreground and startSymServer
  startDiskCache = config['DiskCache']['start'] and not diskCacheRunning()
  foregroundDiskCache = foreground and startDiskCache and not foregroundSymServer
  startMemcached = config['memcached']['start'] and not memcachedRunning()
  foregroundMemcached = foreground and startMemcached and \
                        not foregroundSymServer and not foregroundDiskCache

  # This one is easy because it already has an option to start as a daemon
  if startMemcached:
    command = [
      str(config['memcached']['binary']),
      "-U", "0",
      "-l", str(config['memcached']["listenAddress"]),
      "-m", str(config['memcached']["maxMemoryMB"]),
      "-p", str(config['memcached']["port"]),
      "-P", str(MEMCACHED_PIDFILE)
    ]
    if not foregroundMemcached:
      command.append("-d")
    print "Starting memcached with command: {}".format(command)
    if foregroundMemcached:
      subprocess.call(command)
    else:
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
  if startDiskCache:
    command = [
      "python",
      str(DISKCACHE_PATH),
      "--pidfile", str(DISKCACHE_PIDFILE)
    ]
    command.extend(configOptions)
    print "Starting DiskCache with command: {}".format(command)
    if foregroundDiskCache:
      subprocess.call(command)
    else:
      runDaemon(command)

  if config['SymServer']['start'] and not symServerRunning():
    command = [
      "python",
      str(SYMSERVER_PATH),
      "--pidfile", str(SYMSERVER_PIDFILE)
    ]
    command.extend(configOptions)
    print "Starting SymServer with command: {}".format(command)
    if foregroundSymServer:
      subprocess.call(command)
    else:
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

    port = getDiskCacheConfig(config)['port']

    while time.time() < timeoutEnd:
      response = sendGetRequest(port)
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

    port = getSymServerConfig(config)['port']

    while time.time() < timeoutEnd:
      response = sendGetRequest(port)
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

def stopDocker(config, forceStop = False):
  """ Returns |False| on error. If Docker is not configured for restart and
  |forceStop == False|, it will not be stopped and |True| (success) will be
  returned
  """
  if not dockerRunning(config):
    print "Docker already stopped."
    return True

  if not config["Docker"]["restart"] and not forceStop:
    print "Not stopping Docker because it is not configured for restart"
    return True

  dockerApi = getDockerApi(config)
  try:
    dockerApi.stop(container = DOCKER_CONTAINER_NAME)
  except:
    print "Failed to stop Docker"
    return False

  if dockerRunning(config):
    print "Failed to stop Docker"
    return False

  print "Docker stopped"
  return True

def startDocker(config, foreground = False, forceRebuild = False):
  dockerApi = getDockerApi(config)
  oldDockerConfig = getOldDockerConfigString()
  imageInfo = dockerImageInfo(config)
  rebuild = forceRebuild or not imageInfo or oldDockerConfig == None
  if rebuild:
    print "Building Docker image"
    try:
      dockerApi.remove_image(image = DOCKER_IMAGE_NAME, force = True)
    except:
      # Maybe the image just doesn't exist yet
      pass

    for output in dockerApi.build(path = SRC_DIR, tag = DOCKER_IMAGE_NAME):
      pass

  containerInfo = dockerContainerInfo(config)
  dockerConfig = makeDockerConfigString(config)
  if rebuild or not containerInfo or dockerConfig != oldDockerConfig:
    print "Creating Docker Container"
    try:
      dockerApi.remove_container(image = DOCKER_CONTAINER_NAME, force = True)
    except:
      # Maybe the container just doesn't exist yet
      pass

    internalPorts = []
    publishedPortMapping = {}
    if config["memcached"]["start"]:
      port = config["memcached"]["port"]
      internalPorts.append(port)
      if config["Docker"]["publish"]["memcached"]:
        publishedPortMapping[port] = port
    if config["DiskCache"]["start"]:
      port = getDiskCacheConfig(config)["port"]
      internalPorts.append(port)
      if config["Docker"]["publish"]["DiskCache"]:
        publishedPortMapping[port] = port
    if config["SymServer"]["start"]:
      port = getSymServerConfig(config)["port"]
      internalPorts.append(port)
      if config["Docker"]["publish"]["SymServer"]:
        publishedPortMapping[port] = port
    hostConfig = dockerApi.create_host_config(port_bindings = publishedPortMapping)

    quickstartArgs = ["--foreground", "--configJSON", dockerConfig]

    container = dockerApi.create_container(image = DOCKER_IMAGE_NAME,
                                           ports = internalPorts,
                                           host_config = hostConfig,
                                           detach = not foreground,
                                           name = DOCKER_CONTAINER_NAME,
                                           command = quickstartArgs)
    saveDockerCacheFile(dockerConfig)

  if dockerRunning(config):
    print "Docker already running"
  else:
    print "Starting Container"
    dockerApi.start(container = DOCKER_CONTAINER_NAME)

  return True

gDockerApi = None
def getDockerApi(config):
  global gDockerApi
  if gDockerApi:
    return gDockerApi
  gDockerApi = docker.Client(base_url = config["Docker"]["apiSocket"])
  return gDockerApi

def getOldDockerConfigString():
  """ Returns the configuration used to build the last docker container as a
  string. Returns |None| if there is no old configuration
  """
  data = None
  try:
    with open(DOCKER_CACHE_FILE, 'r') as fp:
      data = fp.read()
  except:
    return None
  return data

def saveDockerCacheFile(dockerConfig):
  with open(DOCKER_CACHE_FILE, 'w') as fp:
    fp.write(dockerConfig)

def dockerContainerInfo(config):
  """ Returns a dictionary of container info, or |None| if there is no container
  """
  dockerApi = getDockerApi(config)
  containerInfo = None
  try:
    containerInfo = dockerApi.inspect_container(container = DOCKER_CONTAINER_NAME)
  except:
    return None
  return containerInfo

def dockerRunning(config):
  containerInfo = dockerContainerInfo(config)
  if not containerInfo:
    return False
  if containerInfo["State"]["Status"] == "running":
    return True
  return False

def dockerImageInfo(config):
  """ Returns a dictionary of image info, or |None| if there is no image
  """
  dockerApi = getDockerApi(config)
  imageInfo = None
  try:
    imageInfo = dockerApi.inspect_image(container = DOCKER_IMAGE_NAME)
  except:
    return None
  return imageInfo

def makeDockerConfigString(config):
  """ Make the configuration to pass to the quickstart within Docker
  """
  if "configPath" in config:
    with open(config["configPath"], "r") as fp:
      dockerConfig = fp.read()
  elif "configJSON" in config:
    dockerConfig = config["configJSON"]
  else:
    raise KeyError("No configuration source in quickstart configuration "
      "(Should contain 'configPath' or 'configJSON')")
  dockerConfig = json.loads(dockerConfig)
  dockerConfig["quickstart"]["Docker"]["enable"] = False # No recursing!
  dockerConfig = json.dumps(dockerConfig, sort_keys = True)
  return dockerConfig

gDiskCacheConfig = None
def getDiskCacheConfig(config):
  global gDiskCacheConfig
  if gDiskCacheConfig:
    return gDiskCacheConfig
  # The config may not have a value for |port|. By loading the config the same
  # way that DiskCache loads it, we guarantee that we have the same value
  # that it has.
  if 'configPath' in config:
    DiskCache.config.loadFile(config['configPath'])
  elif 'configJSON' in config:
    DiskCache.config.loadJSON(config['configJSON'])
  gDiskCacheConfig = DiskCache.config
  return gDiskCacheConfig

gSymServerConfig = None
def getSymServerConfig(config):
  global gSymServerConfig
  if gSymServerConfig:
    return gSymServerConfig
  # The config may not have a value for |port|. By loading the config the same
  # way that SymServer loads it, we guarantee that we have the same value
  # that it has.
  if 'configPath' in config:
    SymServer.config.loadFile(config['configPath'])
  elif 'configJSON' in config:
    SymServer.config.loadJSON(config['configJSON'])
  gSymServerConfig = SymServer.config
  return gSymServerConfig

if __name__ == '__main__':
  multiprocessing.freeze_support()
  sys.exit(main())

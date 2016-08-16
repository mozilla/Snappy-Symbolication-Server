#!/usr/bin/env python
################################################################################
# DiskCache
# 
# Provides a service for retrieving address symbolication data. If the
# requested symbolication data is in the cache, it will be returned from it. If
# not, the needed file will be retrieved and added to the cache.
#
# This cache uses a LRU eviction policy.
################################################################################
from logger import logger, logLevel
from DiskCache_Config import config
from DiskCache_RequestHandler import RequestHandler

import sys
import os
import argparse
import tornado.ioloop
import tornado.web

# Sets configuration and calls |runServer|
def main():
  parser = argparse.ArgumentParser(description = "Run a disk cache server")
  group = parser.add_mutually_exclusive_group()
  group.add_argument('--config', '-c', metavar = "PATH", help = "Path to the "
    "config JSON file. Note that configuration options are overridden by "
    "command line options.")
  group.add_argument('--configJSON', metavar = "JSON", help = "Literal JSON to "
    "load configuration from rather than a configuration file")
  parser.add_argument('--cachePath', '-d', metavar = "PATH", help = "The "
    "directory to save cache data to. Existing data in the directory will be "
    "loaded into the cache. (default: {})"
    .format(os.path.basename(config['cachePath'])))
  parser.add_argument('--localSymbols', '-s', metavar = "PATH",
    action = "append", help = "Adds directory to the list of directories to be "
    "searched for local symbols. This argument can be specified more than "
    "once. By default, no directories are searched.")
  parser.add_argument('--maxSize', '-m', metavar = "SIZE", type = int,
    help = "An integer representing the maximum size of the cache in "
    "megabytes. Note that the cache may, at times, be larger than this. See "
    "the documentation for details. (default: {})".format(config['maxSizeMB']))
  parser.add_argument('--port', '-p', type = int, help = "An integer "
    "representing the port number to listen for requests on. (default: {})"
    .format(config['port']))
  parser.add_argument('--symbolURL', '-u', metavar = "URL", action = "append",
    help = "Adds a URL to the list of URLs to attempt to request symbol files "
    "from. Symbol URLs will always be queried in order. If specified, the "
    "default URL(s) will be discarded. This argument can be specified more "
    "than once (default: {})".format(config['symbolURLs']))
  parser.add_argument('--logPath', '-l', metavar = "PATH", help = "The path to "
    "save logs to. (default: {})"
    .format(os.path.basename(config['log']['path'])))
  parser.add_argument('--logLevel', '-L', metavar = "LEVEL", type = int,
    help = "The level of logging. Should be an integer between 0 and 50 "
    "inclusive. A higher value means less logging. See "
    "https://docs.python.org/2/library/logging.html#levels for details. "
    "(default: {})".format(config['log']['level']))
  parser.add_argument('--logFiles', metavar = "COUNT", type = int,
    help = "The number of log files to rotate through. Must be an integer. "
    "(default: {})".format(config['log']['maxFiles']))
  parser.add_argument('--logFileSize', metavar = "SIZE", type = int,
    help = "The size (in megabytes) a log can grow to before rolling over to "
    "the next log file. Must be an integer. (default: {})"
    .format(config['log']['maxFileSizeMB']))
  parser.add_argument('--pidfile', help = "If specified, a pid file will be "
    "saved to the path specified.")
  args = parser.parse_args()
  config.loadArgs(args)

  pid = os.getpid()
  print "Starting DiskCache server with PID {}".format(pid)
  if args.pidfile:
    with open(args.pidfile, 'w') as fp:
      fp.write(str(pid))

  return runServer()

# Runs server as specified by the |config| object
def runServer():
  logger.configure(
    path = config["log"]["path"],
    level = config["log"]["level"],
    maxFiles = config["log"]["maxFiles"],
    maxFileBytes = config["log"]["maxFileSizeMB"] * 1024 * 1024
  )
  logger.log(logLevel.INFO, "Configuration loaded: {}".format(config))
  app = tornado.web.Application([(r"/", RequestHandler)])
  app.listen(config['port'])
  tornado.ioloop.IOLoop.current().start()

if __name__ == '__main__':
  sys.exit(main())

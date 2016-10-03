#!/usr/bin/env python
################################################################################
# SymServer
#
# Provides a service for retrieving address symbolication data. Uses two sources
# of caching, memcached and DiskCache
################################################################################
from logger import logger, logLevel
from SymServer_Config import config
from SymServer_RequestHandler import RequestHandler

import sys
import os
import argparse
import tornado.ioloop
import tornado.web


# Sets configuration and calls |runServer|
def main():
    parser = argparse.ArgumentParser(description="Run a symbolication server")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--config', '-c', metavar="PATH", help="Path to the "
                       "config JSON file. Note that configuration options are overridden by "
                       "command line options.")
    group.add_argument('--configJSON', metavar="JSON", help="Literal JSON to "
                       "load configuration from rather than a configuration file")
    parser.add_argument('--port', '-p', type=int, help="An integer "
                        "representing the port number to listen for requests on. (default: {})"
                        .format(config['port']))
    parser.add_argument('--memcachedServer', '-m', metavar="ADDRESS",
                        action="append", help="Adds an address to the list of addresses to "
                        "responding to memcached requests. If specified, the default address(es) "
                        "will be discarded. This argument can be specified more than once. To "
                        "prevent using any memcached server, use '-m None'. (default: {})"
                        .format(config['memcachedServers']))
    parser.add_argument('--diskCacheServer', '-d', metavar="ADDRESS",
                        help="Sets the address of the disk cache server. It is required that "
                        "SymServer be able to contact a disk cache server. (default: {})"
                        .format(config['DiskCacheServer']))
    parser.add_argument('--logPath', '-l', metavar="PATH", help="The path to "
                        "save logs to. (default: {})"
                        .format(os.path.basename(config['log']['path'])))
    parser.add_argument('--logLevel', '-L', metavar="LEVEL", type=int,
                        help="The level of logging. Should be an integer between 0 and 50 "
                        "inclusive. A higher value means less logging. See "
                        "https://docs.python.org/2/library/logging.html#levels for details. "
                        "(default: {})".format(config['log']['level']))
    parser.add_argument('--logFiles', metavar="COUNT", type=int,
                        help="The number of log files to rotate through. Must be an integer. "
                        "(default: {})".format(config['log']['maxFiles']))
    parser.add_argument('--logFileSize', metavar="SIZE", type=int,
                        help="The size (in megabytes) a log can grow to before rolling over to "
                        "the next log file. Must be an integer. (default: {})"
                        .format(config['log']['maxFileSizeMB']))
    parser.add_argument('--pidfile', help="If specified, a pid file will be "
                        "saved to the path specified.")
    args = parser.parse_args()
    config.loadArgs(args)

    pid = os.getpid()
    print "Starting SymServer server with PID {}".format(pid)
    if args.pidfile:
        with open(args.pidfile, 'w') as fp:
            fp.write(str(pid))

    return runServer()


# Runs server as specified by the |config| object
def runServer():
    logger.configure(path=config["log"]["path"],
                     level=config["log"]["level"],
                     maxFiles=config["log"]["maxFiles"],
                     maxFileBytes=config["log"]["maxFileSizeMB"] * 1024 * 1024)
    logger.log(logLevel.INFO, "Configuration loaded: {}".format(config))
    app = tornado.web.Application([(r"/", RequestHandler)])
    app.listen(config['port'])
    tornado.ioloop.IOLoop.current().start()

if __name__ == '__main__':
    sys.exit(main())

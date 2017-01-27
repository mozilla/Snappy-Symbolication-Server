from logger import logger, logLevel
from SymServer_Config import config

import sys
import json
import threading
from concurrent.futures import Future
import memcache
import urllib
import urllib2
import contextlib
import traceback


class Symbolicator:
    def __init__(self):
        # Don't init anything that needs config now, because it may not be ready yet
        self.initialized = False
        self.memcache = None
        self.outputCacheHits = False

    def initialize(self):
        self.initialized = True
        if config['memcachedServers']:
            self.memcache = memcache.Client(config['memcachedServers'], debug=0)
        else:
            self.memcache = None

    def symbolicate(self, request, id):
        if not self.initialized:
            self.initialize()
        future = Future()
        if 'debug' in request:
            action = request['action']
            if action == "outputCacheHits":
                self.outputCacheHits = bool(request['enabled'])
                logger.log(logLevel.WARNING, "{} outputCacheHits set to: {}"
                           .format(id, self.outputCacheHits))
                future.set_result({"success": True})
                return future
            # If the action was not recognized, fall through to let the symbolication
            # thread handle it
        symbolicationThread = SymbolicationThread(request, future, self.memcache,
                                                  id, self.outputCacheHits)
        symbolicationThread.start()
        return future


class SymbolicationThread(threading.Thread):
    def __init__(self, request, future, memcache, id, outputCacheHits):
        threading.Thread.__init__(self)
        self.request = request
        self.future = future
        self.memcache = memcache
        self.id = id
        self.outputCacheHits = outputCacheHits
        self.response = self.makeResponseTemplate()

    def log(self, level, message):
        # Put the id at the beginning of all log messages
        logger.log(level, "{} {}".format(self.id, message))

    def makeResponseTemplate(self):
        if 'debug' in self.request:
            return {}
        response = {
            'symbolicatedStacks': [],
            'knownModules': [False] * len(self.request['memoryMap'])
        }
        memoryMap = self.request['memoryMap']
        for stack in self.request['stacks']:
            responseStack = []
            for frameModuleIndex, frameOffset in stack:
                if frameModuleIndex < 0:
                    responseStack.append(hex(frameOffset))
                else:
                    module = memoryMap[frameModuleIndex][0]
                    responseStack.append("{} (in {})".format(hex(frameOffset), module))
            response['symbolicatedStacks'].append(responseStack)
        if self.outputCacheHits:
            response['cacheHits'] = []
            for stack in self.request['stacks']:
                hitsInStack = [False] * len(stack)
                response['cacheHits'].append(hitsInStack)
        return response

    def run(self):
        try:
            if 'debug' in self.request:
                self.debugRequest()
                response = self.response
            else:
                self.symbolicateRequest()
                response = self.response
                if self.request['version'] == 3:
                    response = response['symbolicatedStacks']

            self.future.set_result(response)
        except Exception as e:
            ex_type, ex, tb = sys.exc_info()
            stack = traceback.extract_tb(tb)
            self.log(logLevel.ERROR,
                     "Thread caught exception while symbolicating: {}: {} STACK: {}"
                     .format(ex_type, e, stack))
            self.future.set_exception(e)

    def symbolicateRequest(self):
        subRequest = {
            'stacks': [[]],
            'memoryMap': [],
            'version': 4
        }
        subRequestStack = subRequest['stacks'][0]
        subRequestMemoryMap = subRequest['memoryMap']
        subRequestModuleIndex = {}
        unresolvedFrames = []
        memoryMap = self.request['memoryMap']
        responseStack = self.response['symbolicatedStacks']
        responseKnownModules = self.response['knownModules']

        runIt = self.future.set_running_or_notify_cancel()
        if not runIt:
            self.log(logLevel.DEBUG, "Thread work was cancelled")
            return
        for stackIndex, stack in enumerate(self.request['stacks']):
            for frameIndex, frame in enumerate(stack):
                moduleIndex, offset = frame
                if moduleIndex < 0:
                    continue

                module = memoryMap[moduleIndex]
                module = (module[0], module[1])  # Lists can't be hashed. Tuples can.
                moduleOffsetId = self.moduleOffsetId(module, offset)

                cacheResult = None
                if self.memcache:
                    cacheResult = self.memcache.get(moduleOffsetId)
                if cacheResult is not None:
                    responseStack[stackIndex][frameIndex] = cacheResult
                    responseKnownModules[moduleIndex] = True
                    if self.outputCacheHits:
                        self.response['cacheHits'][stackIndex][frameIndex] = True
                    continue

                # Cache miss. Need to get the value from the DiskCache
                subRequestStack.append(frame)
                subRequestIndex = len(subRequestStack) - 1
                unresolvedFrames.append((stackIndex, frameIndex, moduleIndex, subRequestIndex))
                if module in subRequestModuleIndex:
                    # This module is already in the subRequest. Just reference the
                    # existing module
                    subRequestStack[subRequestIndex][0] = subRequestModuleIndex[module]
                else:
                    # Need to add this module to the subRequest memory map
                    subRequestMemoryMap.append(module)
                    subRequestModuleIndex[module] = len(subRequestMemoryMap) - 1
                    subRequestStack[subRequestIndex][0] = subRequestModuleIndex[module]

        if unresolvedFrames:
            self.log(logLevel.INFO, "{} frames in not in memcached"
                     .format(len(unresolvedFrames)))

            cacheResponse = self.queryDiskCache(subRequest)
            if cacheResponse:
                stack = cacheResponse['symbolicatedStacks'][0]
                knownModules = cacheResponse['knownModules']
                for frame in unresolvedFrames:
                    stackIndex, frameIndex, moduleIndex, subRequestIndex = frame
                    module = memoryMap[moduleIndex]
                    module = (module[0], module[1])  # Lists can't be hashed. Tuples can.
                    moduleKnown = knownModules[subRequestModuleIndex[module]]
                    if moduleKnown:
                        symbol = stack[subRequestIndex]
                        offset = self.request['stacks'][stackIndex][frameIndex][1]
                        moduleOffsetId = self.moduleOffsetId(module, offset)
                        responseStack[stackIndex][frameIndex] = symbol
                        responseKnownModules[moduleIndex] = True
                        if self.memcache:
                            self.memcache.add(moduleOffsetId, symbol)
            else:
                self.log(logLevel.ERROR, "Bad response from DiskCache")

    def moduleOffsetId(self, module, offset):
        # Use quote_plus to ensure there is no whitespace since memcached does not
        # like that
        return "/".join([
            urllib.quote_plus(str(module[0])),
            urllib.quote_plus(str(module[1])),
            urllib.quote_plus(str(offset))
        ])

    def queryDiskCache(self, requestData):
        self.log(logLevel.DEBUG, "Sending request to DiskCache: {}".format(requestData))
        try:
            request = urllib2.Request(config['DiskCacheServer'])
            request.add_data(json.dumps(requestData))
            with contextlib.closing(urllib2.urlopen(request)) as response:
                if response.getcode() != 200:
                    self.log(logLevel.WARNING, "Got HTTP Code {} when querying DiskCache"
                             .format(response.getcode()))
                    return None
                return json.loads(response.read())
        except Exception as e:
            self.log(logLevel.ERROR, "Exception when querying DiskCache: {}".format(e))
            return None

    def debugRequest(self):
        request = self.request
        action = request['action']
        if 'libName' in request and 'breakpadId' in request and 'offset' in request:
            # Many debug actions require a cache id
            cacheId = self.moduleOffsetId((request['libName'], request['breakpadId']),
                                          request['offset'])

        if action == "cacheEvict":
            self.memcache.delete(cacheId)
            self.log(logLevel.WARNING, "{} Cache item manually evicted: {}"
                     .format(self.id, cacheId))
            self.response['success'] = True
        else:
            self.log(logLevel.ERROR, "{} Unknown debug action requested: {}"
                     .format(self.id, action))
            self.response['message'] = "Invalid action"

symbolicator = Symbolicator()

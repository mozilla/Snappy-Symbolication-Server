from logger import logger, logLevel
from DiskCache_Config import config

import sys
import os
import threading
from concurrent.futures import Future
import Queue
import traceback
import urllib
import urllib2
import contextlib
from StringIO import StringIO
import gzip
import zlib
import time


class DiskCache:
    def __init__(self):
        self.workQueue = Queue.Queue()
        self.diskCacheThread = DiskCacheThread(self.workQueue)
        self.diskCacheStarted = False

    def request(self, request, id):
        if not self.diskCacheStarted:
            self.diskCacheStarted = True
            self.diskCacheThread.start()

        future = Future()
        response = self.makeResponseTemplate(request)
        workObject = [str(id), request, response, future]

        self.workQueue.put(workObject)
        logger.log(logLevel.DEBUG,
                   "{} Work submitted to DiskCache thread".format(id))

        return future

    def makeResponseTemplate(self, request):
        if 'debug' in request:
            return {}
        response = {
            'symbolicatedStacks': [],
            'knownModules': [False] * len(request['memoryMap'])
        }
        memoryMap = request['memoryMap']
        for stack in request['stacks']:
            responseStack = []
            for frameModuleIndex, frameOffset in stack:
                module = memoryMap[frameModuleIndex][0]
                responseStack.append("{} (in {})".format(hex(frameOffset), module))
            response['symbolicatedStacks'].append(responseStack)
        return response


class DiskCacheThread(threading.Thread):
    def __init__(self, workQueue):
        threading.Thread.__init__(self)
        self.asyncWorkQueue = workQueue
        # The Queue type of queue only allows items to be put in and pulled out
        # I want to concurrency benefits associated with the Queue, but I also want
        # to be able to examine other enqueued work while working. Therefore we will
        # transfer work items from the Queue to a regular list
        self.workQueue = []
        # config may not be loaded during __init__. Initialize data from config in
        # self.run()
        self.symbolURLs = []
        self.cache = None  # LRUCache also needs config
        self.staticCache = {}

    def init(self):
        if not os.path.exists(config['cachePath']):
            os.makedirs(config['cachePath'])
        self.symbolURLs = config['symbolURLs']
        self.cache = LRUCache()
        self.loadCache()
        self.loadStaticCache()

    def loadCache(self):
        cacheDir = config['cachePath']
        for root, dirs, files in os.walk(cacheDir):
            for file in files:
                path = os.path.join(root, file)
                self.cache.add(path)

    def loadStaticCache(self):
        # Load from directories in reverse order so that directories listed earlier
        # overwrite entries from directories listed later.
        for cacheDir in reversed(config['localSymbolDirs']):
            for root, dirs, files in os.walk(cacheDir):
                relRoot = os.path.relpath(root, cacheDir)
                for file in files:
                    relPath = os.path.join(relRoot, file)
                    path = os.path.join(root, file)
                    self.staticCache[relPath] = path

    def run(self):
        self.init()

        while True:
            id = "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
            future = None
            with self.firstCacheItem():     # Make SURE that we pop the first cache item
                                            # off the work queue even if we fail. We don't
                                            # want to keep processing it over and over.
                try:
                    self.transferWorkQueue(needOne=True)
                    id, request, response, future = self.workQueue[0]
                    runIt = future.set_running_or_notify_cancel()
                    if not runIt:
                        logger.log(logLevel.DEBUG, "{} Thread work was cancelled".format(id))
                        continue

                    logger.log(logLevel.DEBUG, "{} Thread got work".format(id))
                    if 'debug' in request:
                        response = self.doDebugWork()
                    else:
                        response = self.symbolicateFirstQueueEntry()
                    logger.log(logLevel.DEBUG, "{} Thread work done".format(id))

                    future.set_result(response)
                except Exception as e:
                    ex_type, ex, tb = sys.exc_info()
                    stack = traceback.extract_tb(tb)
                    logger.log(logLevel.ERROR,
                               "{} Thread caught exception while working: {}: {} STACK: {}"
                               .format(id, ex_type, e, stack))
                    if future:
                        future.set_exception(e)
                    continue

    @contextlib.contextmanager
    def firstCacheItem(self):
        yield
        self.workQueue.pop(0)

    def transferWorkQueue(self, needOne=False):
        if len(self.workQueue) > 0 and needOne:
            # We need one, but we already have one!
            needOne = False

        workObj = self.getFromAsyncQueue(block=needOne)
        while workObj:
            self.workQueue.append(workObj)
            workObj = self.getFromAsyncQueue(block=False)

    def getFromAsyncQueue(self, block):
        try:
            item = self.asyncWorkQueue.get(block=block)
        except Queue.Empty:
            item = None
        return item

    # Symbolicates the first request in the queue and returns a response. Also
    # symbolicates any frames from other requests if they use the same file so
    # that we don't have to re-read the whole symbol file again when we get to
    # the next request
    # Assumes that the first request in the queue is not a debug request
    def symbolicateFirstQueueEntry(self):
        id, request, response, future = self.workQueue[0]
        for moduleIndex, module in enumerate(request['memoryMap']):
            libName, breakpadId = module

            if response['knownModules'][moduleIndex]:
                # Frames in this module were already symbolicated
                continue

            # Find frames from all requests that use this module
            frameIndicies, offsets = self.findAllFramesReferencingModule(moduleIndex,
                                                                         libName,
                                                                         breakpadId)
            if not offsets:
                continue

            # Get symbol file from cache or add it to the cache
            path = self.getFile(libName, breakpadId)
            if not path:
                # Hmm. Looks like we couldn't get these symbols.
                continue

            symbols = self.getSymbols(path, offsets)
            for workIndex, stackIndex, frameIndex, moduleIndex, frameOffset in frameIndicies:
                if frameOffset not in symbols:
                    continue
                workResponse = self.workQueue[workIndex][2]
                workResponse['symbolicatedStacks'][stackIndex][frameIndex] = \
                    symbols[frameOffset] + " (in {})".format(libName)
                workResponse['knownModules'][moduleIndex] = True
            # A significant amount of time may have passed while retrieving that
            # symbol file. If we added new things to the work queue now, we may be
            # able to consolidate requests for the same file later.
            self.transferWorkQueue()
        return self.workQueue[0][2]

    def findAllFramesReferencingModule(self, moduleIndex, libName, breakpadId):
        """ moduleIndex is the index of the module in the memory map of the request
        at the head of the work queue.
        """
        frameIndicies = []
        offsets = set()
        for workIndex, workObj in enumerate(self.workQueue):
            id, request, response, future = workObj
            if 'debug' in request:
                continue
            memoryMap = request['memoryMap']
            stacks = request['stacks']
            if workIndex > 0:
                for m_index, module in enumerate(memoryMap):
                    m_libName, m_breakpadId = module
                    if m_libName == libName and m_breakpadId == breakpadId:
                        moduleIndex = m_index
                        break
                else:
                    # This module is not in this request. Skip to the next request
                    continue
            for stackIndex, stack in enumerate(stacks):
                for frameIndex, frame in enumerate(stack):
                    frameModuleIndex, frameOffset = frame
                    if frameModuleIndex == moduleIndex:
                        frameIndicies.append((workIndex, stackIndex, frameIndex,
                                             moduleIndex, frameOffset))
                        offsets.add(frameOffset)
        return frameIndicies, list(offsets)

    # If the file is in the cache, its path is returned. Otherwise the file is
    # added to the cache.
    def getFile(self, libName, breakpadId):
        symbolFilename = self.getSymbolFileName(libName)
        relPath = self.getSymbolFileRelPath(libName, breakpadId, symbolFilename)

        cachePath = os.path.join(config['cachePath'], relPath)
        cacheResult = self.cache.retrieve(cachePath)
        if cacheResult:
            return cachePath

        if relPath in self.staticCache:
            return self.staticCache[relPath]

        if self.downloadToCache(libName, breakpadId, symbolFilename, cachePath):
            return cachePath

        return None

    def getSymbolFileName(self, libName):
        if libName.endswith(".pdb"):
            return libName[:-4] + ".sym"
        return libName + ".sym"

    def getSymbolFileRelPath(self, libName, breakpadId, fileName):
        path = os.path.join(libName, breakpadId, fileName)
        return path

    def downloadToCache(self, libName, breakpadId, symbolFilename, destPath, saveRaw=False):
        success, data = self.retrieveFile(libName, breakpadId, symbolFilename)
        if not success:
            return False

        if not saveRaw:
            libId = "{}/{}/{}".format(libName, breakpadId, symbolFilename)
            data = data.splitlines()
            data = self.makeSymMap(data, libId)
        try:
            destDir = os.path.dirname(destPath)
            if not os.path.exists(destDir):
                os.makedirs(destDir)
            with open(destPath, 'wb') as fp:
                fp.write(data)
        except (OSError, IOError) as e:
            logger.log(logLevel.ERROR, "Failed to write file {}: {}".format(destPath, e))
            return False
        self.cache.add(destPath)
        return True

    def retrieveFile(self, libName, breakpadId, symbolFilename):
        """ Returns a tuple: |success, data|
        """
        skipURLs = []
        for attempt in xrange(config['retries']):
            for symbolURL in self.symbolURLs:
                if symbolURL in skipURLs:
                    continue
                url = self.getSymbolURL(symbolURL, libName, breakpadId, symbolFilename)
                success, exists, data = self.fetchURL(url)

                if not success:
                    continue
                if not exists:
                    # Don't retry this server if we know the file is not on it
                    skipURLs.append(symbolURL)
                    continue
                return True, data
            if config['retryDelayMs']:
                time.sleep(config['retryDelayMs'] / 1000)
            logger.log(logLevel.DEBUG,
                       "Retrying download of {}/{}/{}".format(libName, breakpadId, symbolFilename))
        logger.log(logLevel.DEBUG,
                   "Unable to download {}/{}/{}".format(libName, breakpadId, symbolFilename))
        return False, ""

    def fetchURL(self, url):
        """ Retrieves a remote file. Returns a tuple: |success, exists, response|
        |exists| will be set to |True| if the response is a 404 error.
        |success| will be set to |False| if an exception occurs during the request or
        the request received has a code other than 404 or 200. Code 404 is considered
        a success because we successfully learned that the file does not exist on
        the server.
        |response| will be a string of response data. If |exists| or |success| is
        |True|, the response string will be empty.
        """
        try:
            with contextlib.closing(urllib2.urlopen(url)) as response:
                responseCode = response.getcode()
                if responseCode == 404:
                    logger.log(logLevel.DEBUG,
                               "Got HTTP Code 404 when requesting symbol file at {}".format(url))
                    return True, False, ""
                if responseCode != 200:
                    logger.log(logLevel.WARNING,
                               "Got HTTP Code {} when requesting symbol file at {}"
                               .format(responseCode, url))
                    return False, False, ""
                return True, True, self.decodeResponse(response)
        except IOError as e:
            logger.log(logLevel.ERROR,
                       "Exception when requesting symbol file at {}: {}".format(url, e))
            return False, False, ""

    def decodeResponse(self, response):
        headers = response.info()
        contentEncoding = headers.get("Content-Encoding", "").lower()
        if contentEncoding in ("gzip", "x-gzip", "deflate"):
            with contextlib.closing(StringIO(response.read())) as dataStream:
                try:
                    with gzip.GzipFile(fileobj=dataStream) as f:
                        return f.read()
                except zlib.error:
                    return dataStream.decode('zlib')
        return response.read()

    def getSymbolURL(self, symbolURL, libName, breakpadId, fileName):
        # The symbol URL must end with a "/" for this to work. This is why we added
        # slashes to the ends of the URLs at config load.
        return str(symbolURL) + "/".join([
            urllib.quote_plus(libName),
            urllib.quote_plus(breakpadId),
            urllib.quote_plus(fileName)
        ])

    def makeSymMap(self, data, libId):
        symMap = {}
        lineNum = 0
        for line in data:
            lineNum += 1
            if line.startswith("PUBLIC "):
                line = line.rstrip()
                fields = line.split(" ", 3)
                if len(fields) < 4:
                    logger.log(logLevel.WARNING,
                               "PUBLIC line {} in {} has too few fields"
                               .format(lineNum, libId))
                    continue
                address = int(fields[1], 16)
                symbol = fields[3]
                symMap[address] = symbol
            elif line.startswith("FUNC "):
                line = line.rstrip()
                fields = line.split(" ", 4)
                if len(fields) < 5:
                    logger.log(logLevel.WARNING,
                               "FUNC line {} in {} has too few fields"
                               .format(lineNum, libId))
                    continue
                address = int(fields[1], 16)
                symbol = fields[4]
                symMap[address] = symbol
        sortedAddresses = sorted(symMap.keys(), reverse=True)
        symmapString = "DiskCache v.1\n"
        for address in sortedAddresses:
            symmapString += "{} {}\n".format(hex(address), symMap[address])
        return symmapString

    def getSymbols(self, path, offsets):
        if not offsets:
            return {}
        symbols = {}
        try:
            with open(path, 'r') as symFile:
                firstLine = symFile.next().rstrip()
                if firstLine == "DiskCache v.1":
                    # Special DiskCache symbol file
                    offsets.sort(reverse=True)
                    nextOffset = offsets.pop(0)

                    for line in symFile:
                        line = line.rstrip()
                        address, symbol = line.split(" ", 1)
                        address = int(address, 16)
                        while address <= nextOffset:
                            symbols[nextOffset] = symbol
                            if not offsets:
                                return symbols
                            nextOffset = offsets.pop(0)
                elif firstLine.startswith("MODULE "):
                    # Regular symbol file
                    offsets = [[o, None] for o in offsets]
                    lineNum = 1
                    for line in symFile:
                        lineNum += 1
                        if line.startswith("PUBLIC "):
                            line = line.rstrip()
                            fields = line.split(" ", 3)
                            if len(fields) < 4:
                                logger.log(logLevel.WARNING,
                                           "PUBLIC line {} in {} has too few fields"
                                           .format(lineNum, path))
                                continue
                            address = int(fields[1], 16)
                            symbol = fields[3]
                            for index in xrange(len(offsets)):
                                offset, closest = offsets[index]
                                if address <= offset and (closest is None or address > closest):
                                    offsets[index] = [offset, address]
                                    symbols[offset] = symbol
                        elif line.startswith("FUNC "):
                            line = line.rstrip()
                            fields = line.split(" ", 4)
                            if len(fields) < 5:
                                logger.log(logLevel.WARNING,
                                           "FUNC line {} in {} has too few fields"
                                           .format(lineNum, path))
                                continue
                            address = int(fields[1], 16)
                            symbol = fields[4]
                            for index in xrange(len(offsets)):
                                offset, closest = offsets[index]
                                if address <= offset and (closest is None or address > closest):
                                    offsets[index] = [offset, address]
                                    symbols[offset] = symbol
                else:
                    logger.log(logLevel.ERROR,
                               "Unrecognizable type of symbol file {}".format(path))
        except Exception as e:
            ex_type, ex, tb = sys.exc_info()
            stack = traceback.extract_tb(tb)
            logger.log(logLevel.ERROR,
                       "Exception when reading symbols from {}: {} STACK: {}"
                       .format(path, e, stack))
        return symbols

    # Carries out the debug action specified by the first request in the work
    # queue.
    # Assumes that the first request in the queue is a debug request
    def doDebugWork(self):
        id, request, response, future = self.workQueue[0]
        action = request['action']
        logger.log(logLevel.INFO, "{} Handling debug action: {}".format(id, action))
        if 'libName' in request and 'breakpadId' in request:
            # Lots of requests require the cache path for a library
            libName = str(request['libName'])
            breakpadId = str(request['breakpadId'])
            symbolFilename = self.getSymbolFileName(libName)
            relPath = self.getSymbolFileRelPath(libName, breakpadId, symbolFilename)
            cachePath = os.path.join(config['cachePath'], relPath)

        if action == "cacheAddRaw":
            self.cache.evict(cachePath)
            if self.downloadToCache(libName, breakpadId, symbolFilename, cachePath,
                                    saveRaw=True):
                response['path'] = cachePath
            else:
                response['path'] = None
        elif action == "cacheGet":
            response['path'] = self.getFile(libName, breakpadId)
        elif action == "cacheEvict":
            self.cache.evict(cachePath)
            response['success'] = True
        elif action == "cacheExists":
            response['exists'] = (self.cache.retrieve(cachePath) is not None)
        else:
            logger.log(logLevel.ERROR, "{} Invalid action: {}".format(id, action))
            response['message'] = "Invalid action"
        return response


class LRUCache:
    def __init__(self):
        self.cache = {}
        self.oldestEntry = None
        self.newestEntry = None
        self.size = 0
        self.maxSize = config['maxSizeMB'] * 1024 * 1024

    def iterator(self, newestFirst=True):
        if newestFirst:
            current = self.oldestEntry
            while current:
                yield current
                current = current.newer
        else:
            current = self.newestEntry
            while current:
                yield current
                current = current.older

    # For testing/logging
    def toString(self, newestFirst=True):
        output = "["
        firstEntry = True
        for entry in self.iterator(newestFirst):
            if firstEntry:
                firstEntry = False
            else:
                output += ", "
            output += os.path.relpath(entry.path, config['cachePath'])
        output += "]"
        return output

    def retrieve(self, key):
        if key not in self.cache:
            return None
        entry = self.cache[key]
        if entry is not self.newestEntry:
            if entry is self.oldestEntry:
                self.oldestEntry = entry.newer
            # Detatch entry from list
            if entry.older:
                entry.older.newer = entry.newer
            if entry.newer:
                entry.newer.older = entry.older
            # Put entry at the end of the list
            entry.newer = None
            entry.older = self.newestEntry
            self.newestEntry = entry
        return entry

    def add(self, path):
        logger.log(logLevel.DEBUG, "Adding {} to cache".format(path))
        newEntry = CacheEntry(path)
        newEntry.older = self.newestEntry
        if self.newestEntry:
            self.newestEntry.newer = newEntry
        self.newestEntry = newEntry
        if not self.oldestEntry:
            self.oldestEntry = newEntry
        self.size += newEntry.size
        self.cache[path] = newEntry
        while self.size > self.maxSize and newEntry is not self.oldestEntry:
            self.evictOldest()

    def evictOldest(self):
        if not self.oldestEntry:
            return
        toEvict = self.oldestEntry
        logger.log(logLevel.DEBUG, "Evicting {} from the cache (cache size = {})"
                   .format(toEvict.path, self.size))
        self.oldestEntry = toEvict.newer
        if self.oldestEntry:
            self.oldestEntry.older = None
        else:
            self.newestEntry = None
        del self.cache[toEvict.path]
        self.size -= toEvict.size
        try:
            os.remove(toEvict.path)
        except:
            logger.log(logLevel.ERROR, "Unable to delete file evicted from cache: {}"
                       .format(toEvict.path))

    def evict(self, key):
        if key not in self.cache:
            return
        toEvict = self.cache[key]
        logger.log(logLevel.DEBUG,
                   "Evicting {} from the cache by request".format(toEvict.path))
        if toEvict is self.oldestEntry:
            self.oldestEntry = toEvict.newer
            if self.oldestEntry:
                self.oldestEntry.older = None
        if toEvict is self.newestEntry:
            self.newestEntry = toEvict.older
            if self.newestEntry:
                self.newestEntry.newer = None
        del self.cache[toEvict.path]
        self.size -= toEvict.size
        try:
            os.remove(toEvict.path)
        except:
            logger.log(logLevel.ERROR, "Unable to delete file evicted from cache: {}"
                       .format(toEvict.path))


class CacheEntry:
    def __init__(self, path):
        self.path = path
        self.size = os.path.getsize(path)
        self.older = None  # prev pointer
        self.newer = None  # next pointer

diskCache = DiskCache()

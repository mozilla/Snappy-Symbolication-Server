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
import collections
import errno
import sqlite3
import datetime

CACHE_DB_FILENAME = "cache.sqlite"
EPOCH = datetime.datetime.utcfromtimestamp(0)
CACHE_SIZE_BUFFER = 1024 * 1024  # 1 Megabyte

# CacheEntry fields must be in the same order as the SQL table backing it
CacheEntry = collections.namedtuple("CacheEntry", "path size timestamp readers")


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
        self.loadStaticCache()

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

            symbolFilename = self.getSymbolFileName(libName)
            relPath = self.getSymbolFileRelPath(libName, breakpadId, symbolFilename)

            if relPath in self.staticCache:
                path = self.staticCache[relPath]
                symbols = self.getSymbols(path, offsets, inCache=False)
            else:
                path = os.path.join(config['cachePath'], relPath)
                try:
                    symbols = self.getSymbols(path, offsets, inCache=True)
                except LRUCache.NoSuchKey:
                    # Symbol file needs to be downloaded
                    if not self.downloadToCache(libName, breakpadId, symbolFilename, path):
                        continue  # Unable to download
                    symbols = self.getSymbols(path, offsets, inCache=True)

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

        self.cache.add(destPath, data)
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
        publicSymbols = {}
        funcSymbols = {}
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
                publicSymbols[address] = symbol
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
                funcSymbols[address] = symbol
        # Prioritize PUBLIC symbols over FUNC ones
        symMap = funcSymbols
        symMap.update(publicSymbols)

        sortedAddresses = sorted(symMap.keys(), reverse=True)
        symmapString = "DiskCache v.1\n"
        for address in sortedAddresses:
            symmapString += "{} {}\n".format(hex(address), symMap[address])
        return symmapString

    def getSymbols(self, path, offsets, inCache):
        if not offsets:
            return {}
        symbols = {}
        try:
            if inCache:
                with self.cache.fileOpen(path) as symFile:
                    self.readSymbols(path, offsets, symbols, symFile)
            else:
                with open(path, "r") as symFile:
                    self.readSymbols(path, offsets, symbols, symFile)
        except LRUCache.NoSuchKey:
            # Allow NoSuchKey to propagate. All other exceptions should be
            # caught so that if something goes wrong, we fail to symbolicate
            # this frame rather than the whole request.
            raise
        except Exception as e:
            ex_type, ex, tb = sys.exc_info()
            stack = traceback.extract_tb(tb)
            logger.log(logLevel.ERROR,
                       "Exception when reading symbols from {}: {} STACK: {}"
                       .format(path, e, stack))
        return symbols

    def readSymbols(self, path, offsets, symbols, stream):
        firstLine = stream.next().rstrip()
        if firstLine == "DiskCache v.1":
            # Special DiskCache symbol file
            offsets.sort(reverse=True)
            nextOffset = offsets.pop(0)

            for line in stream:
                line = line.rstrip()
                address, symbol = line.split(" ", 1)
                address = int(address, 16)
                while address <= nextOffset:
                    symbols[nextOffset] = symbol
                    if not offsets:
                        return
                    nextOffset = offsets.pop(0)
        elif firstLine.startswith("MODULE "):
            # Regular symbol file
            offsets = [[o, None] for o in offsets]
            lineNum = 1
            for line in stream:
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

        if action == "heartbeat":
            self.cache.touch()
        elif action == "cacheAddRaw":
            try:
                self.cache.evict(cachePath)
            except LRUCache.NoSuchKey:
                pass

            if self.downloadToCache(libName, breakpadId, symbolFilename, cachePath,
                                    saveRaw=True):
                response['path'] = cachePath
            else:
                response['path'] = None
        elif action == "cacheGet":
            if relPath in self.staticCache:
                response['path'] = self.staticCache[relPath]
            else:
                try:
                    self.cache.touchEntry(cachePath)
                    response['path'] = cachePath
                except LRUCache.NoSuchKey:
                    if self.downloadToCache(libName, breakpadId, symbolFilename, cachePath):
                        response['path'] = cachePath
                    else:
                        response['path'] = None
        elif action == "cacheEvict":
            self.cache.evict(cachePath)
            response['success'] = True
        elif action == "cacheExists":
            if relPath in self.staticCache:
                response['exists'] = True
            else:
                try:
                    self.cache.touchEntry(cachePath)
                    response['exists'] = True
                except LRUCache.NoSuchKey:
                    response['exists'] = False
        else:
            logger.log(logLevel.ERROR, "{} Invalid action: {}".format(id, action))
            response['message'] = "Invalid action"
        return response


class LRUCache:
    class NoSuchKey(KeyError):
        pass

    class KeyConflict(KeyError):
        pass

    def __init__(self):
        self.maxSize = config['maxSizeMB'] * 1024 * 1024
        self.path = os.path.join(config['cachePath'], CACHE_DB_FILENAME)
        self.connection = sqlite3.connect(self.path)
        self.cursor = self.connection.cursor()
        self.blockSize = os.statvfs(self.path).f_bsize  # This line only works in Unix systems

        with self.transaction():
            # Fields must be in the same order as the namedtuple: CacheEntry
            self.cursor.execute("CREATE TABLE IF NOT EXISTS cache "
                                "("
                                "      path      TEXT    NOT NULL"
                                "    , size      INTEGER NOT NULL"
                                "    , timestamp INTEGER NOT NULL "
                                "    , readers   INTEGER NOT NULL DEFAULT 0"
                                "    , PRIMARY KEY (path)"
                                ");")

    @contextlib.contextmanager
    def transaction(self):
        # NOTE: Transactions within transactions are NOT SUPPORTED
        self.cursor.execute("BEGIN TRANSACTION;")
        try:
            yield
            self.connection.commit()
        except:
            self.connection.rollback()
            raise

    @contextlib.contextmanager
    def fileOpen(self, path):
        """ This function should ALWAYS be used when accessing files in the
        cache.
        """
        with self.transaction():
            result = self.cursor.execute("UPDATE cache "
                                         "SET readers=readers+1 "
                                         "WHERE path=?;", (path, ))
        if result.rowcount == 0:
            raise self.NoSuchKey("Path not in cache")

        try:
            with open(path, "r") as f:
                yield f
        except (IOError, OSError) as e:
            ex_type, ex, tb = sys.exc_info()
            logger.log(logLevel.ERROR, "Unable to read cache file: {} - {} - {}"
                                       .format(path, ex_type, e))
            # Likely this file was deleted externally without being evicted from
            # the cache. The sanest thing to do is to just evict it now since
            # it is effectively no longer in the cache.
            self.evict(path)
            raise self.NoSuchKey("Path not in cache")
        finally:
            with self.transaction():
                self.cursor.execute("UPDATE cache "
                                    "SET readers=readers-1 "
                                    "  , timestamp=? "
                                    "WHERE path=?", (self.timestamp(), path))

    def touchEntry(self, path):
        with self.transaction():
            result = self.cursor.execute("UPDATE cache "
                                         "SET timestamp=? "
                                         "WHERE path=?;", (self.timestamp(), path))
        if result.rowcount == 0:
            raise self.NoSuchKey("Path not in cache")

    def touch(self):
        """ Makes sure that the cache is available. Should raise an exception if
        it is not.
        """
        self.size()

    def logicalSizeToDiskSize(self, logicalSize):
        blocks = (logicalSize - 1) / self.blockSize + 1
        return blocks * self.blockSize

    def size(self):
        dataSize = self.cursor.execute("SELECT SUM(size) FROM cache;").fetchone()[0]
        if dataSize is None:
            dataSize = 0
        cacheSize = self.logicalSizeToDiskSize(os.path.getsize(self.path))
        totalSize = dataSize + cacheSize
        # Add an arbitrary buffer so that we can ignore changes to the size of
        # the database file and just assume that a single transaction will not
        # increase its size by more than that. A bit hacky, but easier than
        # trying to predict the size changes of the database.
        totalSize += CACHE_SIZE_BUFFER
        return totalSize

    def add(self, path, data):
        dataSize = self.logicalSizeToDiskSize(len(bytearray(data)))

        while True:
            # We want the size request and addition to be in the same
            # transaction to prevent race conditions.
            # To complicate things, however, we want evictions (if necessary),
            # to be their own transactions. We don't want to roll back the
            # evictions if the addition fails (since the files are gone).
            with self.transaction():
                currentSize = self.size()

                if currentSize + dataSize <= self.maxSize:
                    try:
                        self.cursor.execute("INSERT INTO cache (path, size, timestamp) "
                                            "VALUES (?, ?, ?);",
                                            (path, dataSize, self.timestamp()))
                    except sqlite3.IntegrityError:
                        raise self.KeyConflict("That key (path) is already in the cache")

                    try:
                        destDir = os.path.dirname(path)
                        if not os.path.exists(destDir):
                            os.makedirs(destDir)
                        with open(path, "w") as f:
                            f.write(data)
                    except:
                        # On failure, try to clean up, then re-raise
                        ex_type, ex, tb = sys.exc_info()
                        try:
                            self.removeCacheFile(path)
                        except:
                            pass
                        raise ex_type, ex, tb
                    return

            while currentSize + dataSize > self.maxSize:
                evicted = self.evictOldest()
                if evicted is None:
                    raise IOError("Unable to free enough room for new cache file")
                currentSize -= evicted.size

    def evictOldest(self):
        with self.transaction():
            result = self.cursor.execute("SELECT * FROM cache "
                                         "WHERE readers=0 "
                                         "ORDER BY timestamp ASC "
                                         "LIMIT 1;").fetchone()
            if result is None:
                return None

            toEvict = CacheEntry(*result)
            self.cursor.execute("DELETE FROM cache WHERE path=?;", (toEvict.path,))
            try:
                self.removeCacheFile(toEvict.path)
            except:
                # If this fails, unfortunately, there is not much to be done
                # about it. Most likely, the file already doesn't exist, so
                # just commit the transaction and carry on.
                pass
        return toEvict

    def evict(self, path):
        with self.transaction():
            result = self.cursor.execute("DELETE FROM cache WHERE path=?;", (path,))
            if result.rowcount == 0:
                raise self.NoSuchKey("Path not in cache")
            try:
                self.removeCacheFile(path)
            except:
                # If this fails, unfortunately, there is not much to be done
                # about it. Most likely, the file already doesn't exist, so
                # just commit the transaction and carry on.
                pass

    def timestamp(self):
        now = datetime.datetime.utcnow()
        return (now - EPOCH).total_seconds()

    def removeCacheFile(self, path):
        try:
            os.remove(path)
        except Exception as e:
            # Make very sure that this gets logged by catching `Exception`. Failure
            # to remove files will result in the DiskCache filling up with files
            # that are not tracked by the cache.
            ex_type, ex, tb = sys.exc_info()
            logger.log(logLevel.ERROR, "Unable to remove file: {} - {} - {}"
                                       .format(path, ex_type, e))
            raise

        directory = os.path.dirname(path)
        while directory != config["cachePath"]:
            try:
                os.rmdir(directory)
            except OSError as ex:
                if ex.errno == errno.ENOTEMPTY:
                    return
                raise
            directory = os.path.dirname(directory)


diskCache = DiskCache()

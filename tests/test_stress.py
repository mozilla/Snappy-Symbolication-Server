import unittest
import os
import shutil
import json
import threading
import Queue
import time
import random
import memcache

import testUtils
testUtils.addSymServerToPath()
import quickstart

# WARNING: Setting this too high will result in problems with too many handles
# open.
REQUEST_COUNT = 300

TEST_DIR = os.path.dirname(os.path.realpath(__file__))
DISK_CACHE_HIT_REQUEST_PATH = os.path.join(TEST_DIR, "DiskCacheHitRequests.json")
CACHE_MISS_REQUEST_PATH = os.path.join(TEST_DIR, "cacheMissRequests.json")


class StressTest(unittest.TestCase):
    def setUp(self):
        self.config = testUtils.getDefaultConfig()
        self.tempDirs = testUtils.setConfigToUseTempDirs(self.config)
        if not quickstart.quickstart(configJSON=json.dumps(self.config)):
            self.fail("Unable to start servers")
        memcache.Client(self.config['SymServer']['memcachedServers'], debug=0).flush_all()

    def tearDown(self):
        if not quickstart.quickstart(configJSON=json.dumps(self.config), stop=True):
            print "WARNING: Servers were not properly stopped!"
        for tempDir in self.tempDirs:
            if os.path.exists(tempDir):
                shutil.rmtree(tempDir)

    def test_memcachedHitsPrimed(self):
        print "Memcached hits:"
        request = testUtils.sampleRequest()

        requests = []
        expectedResponses = {request: testUtils.sampleResponse()}
        for index in xrange(REQUEST_COUNT):
            requests.append(request)

        print "Priming cache..."
        response = testUtils.symServerRequest(request, "127.0.0.1",
                                              self.config['SymServer']['port'])
        testUtils.verifySampleResponse(self, response)
        print "Done priming cache."

        self.makeRequestsCheckResponses(requests, expectedResponses)

    def test_memcachedHitsUnprimed(self):
        print "Memcached hits:"
        request = testUtils.sampleRequest()

        requests = []
        expectedResponses = {request: testUtils.sampleResponse()}
        for index in xrange(REQUEST_COUNT):
            requests.append(request)

        self.makeRequestsCheckResponses(requests, expectedResponses)

    def test_diskCacheHitsPrimed(self):
        print "DiskCache hits:"
        print "Loading requests/responses..."
        with open(DISK_CACHE_HIT_REQUEST_PATH, 'r') as fp:
            requestData = json.load(fp)
        random.shuffle(requestData)
        primingData = requestData.pop(0)
        # Truncate the list to the desired length
        requestData = requestData[:REQUEST_COUNT]
        expectedResponses = {}
        requests = []

        for data in requestData:
            request = json.dumps(data['request'])
            response = json.dumps(data['response'])
            expectedResponses[request] = response
            requests.append(request)
        del requestData
        print "Done loading requests/responses"

        print "Priming cache..."
        request = json.dumps(primingData['request'])
        expectedResponse = json.dumps(primingData['response'])
        response = testUtils.symServerRequest(request, "127.0.0.1",
                                              self.config['SymServer']['port'])
        testUtils.verifyExpectedResponse(self, expectedResponse, response)
        print "Done priming cache."

        self.makeRequestsCheckResponses(requests, expectedResponses)

    def test_diskCacheHitsUnprimed(self):
        print "DiskCache hits:"
        print "Loading requests/responses..."
        with open(DISK_CACHE_HIT_REQUEST_PATH, 'r') as fp:
            requestData = json.load(fp)
        random.shuffle(requestData)
        # Truncate the list to the desired length
        requestData = requestData[:REQUEST_COUNT]

        expectedResponses = {}
        requests = []
        for data in requestData:
            request = json.dumps(data['request'])
            response = json.dumps(data['response'])
            expectedResponses[request] = response
            requests.append(request)
        del requestData
        print "Done loading requests/responses"

        self.makeRequestsCheckResponses(requests, expectedResponses)

    def test_cacheMisses(self):
        print "Cache misses:"
        print "Loading requests/responses"
        with open(CACHE_MISS_REQUEST_PATH, 'r') as fp:
            requestData = json.load(fp)
        random.shuffle(requestData)
        # Truncate the list to the desired length
        requestData = requestData[:REQUEST_COUNT]

        expectedResponses = {}
        requests = []
        for data in requestData:
            request = json.dumps(data['request'])
            response = json.dumps(data['response'])
            expectedResponses[request] = response
            requests.append(request)
        del requestData
        print "Done loading requests/responses"

        self.makeRequestsCheckResponses(requests, expectedResponses)

    def test_randomPrimed(self):
        print "Random hits/misses:"
        testsPerType = REQUEST_COUNT / 3

        print "Loading requests/responses"
        expectedResponses = {}
        requests = []

        # Memcached hits
        request = testUtils.sampleRequest()
        response = testUtils.sampleResponse()
        for i in xrange(testsPerType):
            requests.append(request)
        expectedResponses[request] = response
        memcachedPrimingRequest = request
        memcachedPrimingReponse = response

        # DiskCache hits
        with open(DISK_CACHE_HIT_REQUEST_PATH, 'r') as fp:
            requestData = json.load(fp)
        random.shuffle(requestData)
        primingData = requestData.pop(0)
        diskCachePrimingRequest = json.dumps(primingData['request'])
        diskCachePrimingResponse = json.dumps(primingData['response'])
        requestData = requestData[:testsPerType]

        for data in requestData:
            request = json.dumps(data['request'])
            response = json.dumps(data['response'])
            expectedResponses[request] = response
            requests.append(request)

        # Cache misses
        with open(CACHE_MISS_REQUEST_PATH, 'r') as fp:
            requestData = json.load(fp)
        random.shuffle(requestData)
        requestData = requestData[:testsPerType]

        for data in requestData:
            request = json.dumps(data['request'])
            response = json.dumps(data['response'])
            expectedResponses[request] = response
            requests.append(request)
        del requestData
        print "Done loading requests/responses"

        print "Priming cache"
        response = testUtils.symServerRequest(memcachedPrimingRequest, "127.0.0.1",
                                              self.config['SymServer']['port'])
        testUtils.verifyExpectedResponse(self, memcachedPrimingReponse, response)
        response = testUtils.symServerRequest(diskCachePrimingRequest, "127.0.0.1",
                                              self.config['SymServer']['port'])
        testUtils.verifyExpectedResponse(self, diskCachePrimingResponse, response)
        print "Done priming cache"

        self.makeRequestsCheckResponses(requests, expectedResponses)

    def test_randomUnprimed(self):
        print "Random hits/misses:"
        testsPerType = REQUEST_COUNT / 3

        print "Loading requests/responses"
        expectedResponses = {}
        requests = []

        # Memcached hits
        request = testUtils.sampleRequest()
        response = testUtils.sampleResponse()
        for i in xrange(testsPerType):
            requests.append(request)
        expectedResponses[request] = response

        # DiskCache hits
        with open(DISK_CACHE_HIT_REQUEST_PATH, 'r') as fp:
            requestData = json.load(fp)
        random.shuffle(requestData)
        requestData = requestData[:testsPerType]

        for data in requestData:
            request = json.dumps(data['request'])
            response = json.dumps(data['response'])
            expectedResponses[request] = response
            requests.append(request)

        # Cache misses
        with open(CACHE_MISS_REQUEST_PATH, 'r') as fp:
            requestData = json.load(fp)
        random.shuffle(requestData)
        requestData = requestData[:testsPerType]

        for data in requestData:
            request = json.dumps(data['request'])
            response = json.dumps(data['response'])
            expectedResponses[request] = response
            requests.append(request)
        del requestData
        print "Done loading requests/responses"

        self.makeRequestsCheckResponses(requests, expectedResponses)

    def makeRequestsCheckResponses(self, requests, expectedResponses):
        startTime = time.time()
        requestThreads = []
        responseQueue = Queue.Queue()
        for request in requests:
            requestThread = RequestThread(request, self.config['SymServer']['port'],
                                          responseQueue)
            requestThreads.append(requestThread)
            requestThread.start()

        for requestThread in requestThreads:
            requestThread.join()
        stopTime = time.time()
        elapsedTime = stopTime - startTime
        print "Handled {} requests in {} seconds".format(len(requests), elapsedTime)

        while not responseQueue.empty():
            request, response = responseQueue.get()
            testUtils.verifyExpectedResponse(self, expectedResponses[request],
                                             response)

        return elapsedTime


class RequestThread(threading.Thread):
    def __init__(self, request, port, responseQueue):
        threading.Thread.__init__(self)
        self.request = request
        self.responseQueue = responseQueue
        self.port = port

    def run(self):
        response = testUtils.symServerRequest(self.request, "127.0.0.1", self.port)
        self.responseQueue.put((self.request, response))

if __name__ == '__main__':
    unittest.main()

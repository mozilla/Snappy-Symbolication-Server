import unittest
import os
import shutil
import json

import testUtils
testUtils.addSymServerToPath()
import quickstart


class SymServerCache(unittest.TestCase):
    def setUp(self):
        self.config = testUtils.getDefaultConfig()
        self.tempDirs = testUtils.setConfigToUseTempDirs(self.config)
        if not quickstart.quickstart(configJSON=json.dumps(self.config)):
            self.fail("Unable to start servers")

    def tearDown(self):
        if not quickstart.quickstart(configJSON=json.dumps(self.config), stop=True):
            print "WARNING: Servers were not properly stopped!"
        for tempDir in self.tempDirs:
            if os.path.exists(tempDir):
                shutil.rmtree(tempDir)

    def test_cache(self):
        request = {
            "debug": True,
            "action": "outputCacheHits",
            "enabled": True
        }
        JSONrequest = json.dumps(request)
        response = testUtils.symServerRequest(JSONrequest, ip="127.0.0.1",
                                              port=self.config['SymServer']['port'])
        response = testUtils.verifyGenericResponse(self, response)
        self.assertIn('success', response, "No result provided in response")

        JSONrequest = testUtils.sampleRequest()
        response = testUtils.symServerRequest(JSONrequest, ip="127.0.0.1",
                                              port=self.config['SymServer']['port'])
        response = testUtils.verifySampleResponse(self, response)
        self.assertIn('cacheHits', response)
        for stackHits in response['cacheHits']:
            for frameHit in stackHits:
                self.assertFalse(frameHit, "Should not have gotten any cache hits "
                                 "right after the server is started")

        response = testUtils.symServerRequest(JSONrequest, ip="127.0.0.1",
                                              port=self.config['SymServer']['port'])
        response = testUtils.verifySampleResponse(self, response)
        self.assertIn('cacheHits', response)
        for stackHits in response['cacheHits']:
            for frameHit in stackHits:
                self.assertTrue(frameHit, "Should not have gotten any cache misses "
                                "on the second query")

        # Evict items from the cache
        request = json.loads(JSONrequest)
        memoryMap = request['memoryMap']
        for stack in request['stacks']:
            for frame in stack:
                moduleId, offset = frame
                libName, breakpadId = memoryMap[moduleId]
                evictRequest = {
                    "debug": True,
                    "action": "cacheEvict",
                    "libName": libName,
                    "breakpadId": breakpadId,
                    "offset": offset
                }
                evictRequest = json.dumps(evictRequest)
                response = testUtils.symServerRequest(evictRequest, ip="127.0.0.1",
                                                      port=self.config['SymServer']['port'])
                response = testUtils.verifyGenericResponse(self, response)
                self.assertIn('success', response,
                              "No result provided in eviction reponse")
                self.assertTrue(response['success'], "Eviction request unsuccessful")

        response = testUtils.symServerRequest(JSONrequest, ip="127.0.0.1",
                                              port=self.config['SymServer']['port'])
        response = testUtils.verifySampleResponse(self, response)
        self.assertIn('cacheHits', response)
        for stackHits in response['cacheHits']:
            for frameHit in stackHits:
                self.assertFalse(frameHit, "Should not have gotten any cache hits "
                                 "right after all cache items are evicted")

        response = testUtils.symServerRequest(JSONrequest, ip="127.0.0.1",
                                              port=self.config['SymServer']['port'])
        response = testUtils.verifySampleResponse(self, response)
        self.assertIn('cacheHits', response)
        for stackHits in response['cacheHits']:
            for frameHit in stackHits:
                self.assertTrue(frameHit, "Should not have gotten any cache misses "
                                "on the second query")

if __name__ == '__main__':
    unittest.main()

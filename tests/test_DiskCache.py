import unittest
import os
import shutil
import json
import memcache

import testUtils
testUtils.addSymServerToPath()
import quickstart

LIB_NAME = "xul.pdb"
BREAKPAD_ID = "44E4EC8C2F41492B9369D6B9A059577C2"
EXPECTED_HASH = "6e5e6e422151b7b557d913c0ff86d7cf"


class testDiskCache(unittest.TestCase):
    def setUp(self):
        self.config = testUtils.getDefaultConfig()
        self.tempDirs = testUtils.setConfigToUseTempDirs(self.config)
        # Only need DiskCache for this one
        self.config['quickstart']['memcached']['start'] = False
        self.config['quickstart']['SymServer']['start'] = False
        if not quickstart.quickstart(configJSON=json.dumps(self.config)):
            self.fail("Unable to start servers")
        memcache.Client(self.config['SymServer']['memcachedServers'], debug=0).flush_all();

    def tearDown(self):
        if not quickstart.quickstart(configJSON=json.dumps(self.config), stop=True):
            print "WARNING: Servers were not properly stopped!"
        for tempDir in self.tempDirs:
            if os.path.exists(tempDir):
                shutil.rmtree(tempDir)

    def test_verifyCachedSymbolFile(self):
        request = {
            "debug": True,
            "action": "cacheAddRaw",
            "libName": LIB_NAME,
            "breakpadId": BREAKPAD_ID
        }
        request = json.dumps(request)
        response = testUtils.symServerRequest(request, ip="127.0.0.1",
                                              port=self.config['DiskCache']['port'])
        response = testUtils.verifyGenericResponse(self, response)
        self.assertIn('path', response, "No path provided in response")
        downloadHash = testUtils.md5(response['path'])
        self.assertEqual(downloadHash.lower(), EXPECTED_HASH.lower(),
                         "Cached symbol file hash does not match the expected hash")

    def test_verifyCache(self):
        # The DiskCache was created with a brand new cache directory. There should
        # be nothing in the cache
        request = {
            "debug": True,
            "action": "cacheExists",
            "libName": LIB_NAME,
            "breakpadId": BREAKPAD_ID
        }
        JSONrequest = json.dumps(request)
        response = testUtils.symServerRequest(JSONrequest, ip="127.0.0.1",
                                              port=self.config['DiskCache']['port'])
        response = testUtils.verifyGenericResponse(self, response)
        self.assertIn('exists', response,
                      "No result provided in response to Exists")
        self.assertFalse(response['exists'],
                         "Value is still in cache after eviction")

        request['action'] = 'cacheAddRaw'
        JSONrequest = json.dumps(request)
        response = testUtils.symServerRequest(JSONrequest, ip="127.0.0.1",
                                              port=self.config['DiskCache']['port'])
        response = testUtils.verifyGenericResponse(self, response)
        self.assertIn('path', response, "No path provided in response to Add")
        downloadHash = testUtils.md5(response['path'])
        self.assertEqual(downloadHash.lower(), EXPECTED_HASH.lower(),
                         "Added symbol file hash does not match the expected hash")

        request['action'] = 'cacheExists'
        JSONrequest = json.dumps(request)
        response = testUtils.symServerRequest(JSONrequest, ip="127.0.0.1",
                                              port=self.config['DiskCache']['port'])
        response = testUtils.verifyGenericResponse(self, response)
        self.assertIn('exists', response,
                      "No result provided in response to Exists")
        self.assertTrue(response['exists'],
                        "Value not in cache after adding")

        request['action'] = 'cacheGet'
        JSONrequest = json.dumps(request)
        response = testUtils.symServerRequest(JSONrequest, ip="127.0.0.1",
                                              port=self.config['DiskCache']['port'])
        response = testUtils.verifyGenericResponse(self, response)
        self.assertIn('path', response, "No path provided in response to Get")
        cachePath = response['path']
        downloadHash = testUtils.md5(cachePath)
        self.assertEqual(downloadHash.lower(), EXPECTED_HASH.lower(),
                         "Added symbol file hash does not match the expected hash")

        request['action'] = 'cacheEvict'
        JSONrequest = json.dumps(request)
        response = testUtils.symServerRequest(JSONrequest, ip="127.0.0.1",
                                              port=self.config['DiskCache']['port'])
        response = testUtils.verifyGenericResponse(self, response)
        self.assertIn('success', response,
                      "No result provided in response to Evict")
        self.assertTrue(response['success'], "Cache eviction unsuccessful.")
        self.assertFalse(os.path.exists(cachePath),
                         "Cache file should not exist after eviction")

        request['action'] = 'cacheExists'
        JSONrequest = json.dumps(request)
        response = testUtils.symServerRequest(JSONrequest, ip="127.0.0.1",
                                              port=self.config['DiskCache']['port'])
        response = testUtils.verifyGenericResponse(self, response)
        self.assertIn('exists', response,
                      "No result provided in response to Exists")
        self.assertFalse(response['exists'],
                         "Value is still in cache after eviction")

        request['action'] = 'cacheGet'
        JSONrequest = json.dumps(request)
        response = testUtils.symServerRequest(JSONrequest, ip="127.0.0.1",
                                              port=self.config['DiskCache']['port'])
        response = testUtils.verifyGenericResponse(self, response)
        self.assertIn('path', response, "No path provided in response to Get")
        # Don't test the md5 hash. We didn't get the raw symbol file.
        self.assertTrue(os.path.exists(response['path']),
                        "Cached file does not exist after a cacheGet")

if __name__ == '__main__':
    unittest.main()

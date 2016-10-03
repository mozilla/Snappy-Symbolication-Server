import os
import sys
import urllib2
import contextlib
import json
import tempfile
import hashlib
from functools import partial

TEST_DIR = os.path.dirname(os.path.realpath(__file__))
TEST_CONFIG_PATH = os.path.join(TEST_DIR, "config.json")

READ_CHUNK_SIZE = 1024


def addSymServerToPath():
    testDir = os.path.dirname(os.path.realpath(__file__))
    quickstartDir = os.path.realpath(os.path.join(testDir, ".."))
    if quickstartDir not in sys.path:
        sys.path.insert(0, quickstartDir)

addSymServerToPath()
import snappy.DiskCache_Config as DiskCache
import snappy.SymServer_Config as SymServer
import snappy.quickstart_Config as quickstart


def symServerRequest(requestString, ip, port):
    try:
        request = urllib2.Request("http://{}:{}".format(ip, port))
        request.add_data(requestString)
        with contextlib.closing(urllib2.urlopen(request)) as response:
            return {'code': response.getcode(), 'data': response.read()}
    except urllib2.HTTPError as err:
        return {'code': err.code, 'data': None}


def sampleRequest():
    request = {
        "stacks": [[[0, 11723767], [1, 65802]]],
        "memoryMap": [
            ["xul.pdb", "44E4EC8C2F41492B9369D6B9A059577C2"],
            ["wntdll.pdb", "D74F79EB1F8D4A45ABCD2F476CCABACC2"]
        ],
        "version": 4
    }
    return json.dumps(request)


def sampleResponse():
    response = {
        "symbolicatedStacks":
        [[
            "XREMain::XRE_mainRun() (in xul.pdb)",
            "KiUserCallbackDispatcher (in wntdll.pdb)"
        ]],
        "knownModules": [True, True]
    }
    return json.dumps(response)


def verifySampleResponse(testCase, response):
    return verifyExpectedResponse(testCase, sampleResponse(), response)


def verifyExpectedResponse(testCase, expected, response):
    response = verifyGenericResponse(testCase, response)
    expected = json.loads(expected)
    testCase.assertIn("symbolicatedStacks", response,
                      "Response JSON should contain symbolicatedStacks")
    testCase.assertIn("knownModules", response,
                      "Response JSON should contain knownModules")
    testCase.assertEqual(len(response['symbolicatedStacks']), len(expected['symbolicatedStacks']),
                         "Response has the incorrect number of symbolicated stacks")
    testCase.assertEqual(len(response['knownModules']), len(expected['knownModules']),
                         "Response has the incorrect number of known modules")
    for i in xrange(len(expected['knownModules'])):
        testCase.assertEqual(response['knownModules'][i], expected['knownModules'][i],
                             "Response has incorrect value for a knownModule")
    for i in xrange(len(expected['symbolicatedStacks'])):
        responseStack = response['symbolicatedStacks'][i]
        expectedStack = expected['symbolicatedStacks'][i]
        testCase.assertEqual(len(responseStack), len(expectedStack),
                             "Response stack has the wrong number of frames")
        for i in xrange(len(expectedStack)):
            responseFrame = responseStack[i]
            expectedFrame = expectedStack[i]
            testCase.assertEqual(responseFrame, expectedFrame,
                                 "Response frame has the incorrect value")
    return response


def verifyGenericResponse(testCase, response):
    testCase.assertEqual(response['code'], 200, "HTTP Status code should be 200")
    testCase.assertNotEqual(response['data'], None,
                            "Server should have returned a response")
    try:
        response = json.loads(response['data'])
    except ValueError:
        testCase.fail("Response should be valid JSON")
    testCase.assertIsInstance(response, dict, "Reponse should be a dictionary")
    return response


def getDefaultConfig():
    diskCacheConfig = DiskCache.Config()
    symServerConfig = SymServer.Config()
    quickstartConfig = quickstart.Config()
    config = {
        "DiskCache": diskCacheConfig,
        "SymServer": symServerConfig,
        "quickstart": quickstartConfig
    }
    try:
        config["DiskCache"].loadFile(TEST_CONFIG_PATH)
    except IOError:
        pass
    try:
        config["SymServer"].loadFile(TEST_CONFIG_PATH)
    except IOError:
        pass
    try:
        config["quickstart"].loadFile(TEST_CONFIG_PATH)
    except IOError:
        pass
    # Some options will be forced so that testing can work as expected
    config['quickstart']['DiskCache']['start'] = True
    config['quickstart']['DiskCache']['restart'] = True
    config['quickstart']['SymServer']['start'] = True
    config['quickstart']['SymServer']['restart'] = True
    config['quickstart']['Docker']['enable'] = False
    return config


def setConfigToUseTempDirs(config):
    logDir = tempfile.mkdtemp()
    cacheDir = tempfile.mkdtemp()
    config['DiskCache']['cachePath'] = cacheDir
    config['DiskCache']['localSymbolDirs'] = []
    config['DiskCache']['log']['path'] = os.path.join(logDir, "DiskCache.log")
    config['SymServer']['log']['path'] = os.path.join(logDir, "SymServer.log")
    return [logDir, cacheDir]


def md5(path):
    hasher = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(partial(f.read, READ_CHUNK_SIZE), ''):
            hasher.update(chunk)
    return hasher.hexdigest()

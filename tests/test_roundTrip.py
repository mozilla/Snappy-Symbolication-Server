import unittest
import os
import shutil
import json

import testUtils
testUtils.addSymServerToPath()
import quickstart

class RoundTrip(unittest.TestCase):
  def setUp(self):
    self.config = testUtils.getDefaultConfig()
    self.tempDirs = testUtils.setConfigToUseTempDirs(self.config)
    if not quickstart.quickstart(configJSON = json.dumps(self.config)):
      self.fail("Unable to start servers")

  def tearDown(self):
    if not quickstart.quickstart(stop = True):
      print "WARNING: Servers were not properly stopped!"
    for tempDir in self.tempDirs:
      if os.path.exists(tempDir):
        shutil.rmtree(tempDir)

  def test_sampleRequest(self):
    request = testUtils.sampleRequest()
    response = testUtils.symServerRequest(request, ip = "127.0.0.1",
      port = self.config['SymServer']['port'])
    testUtils.verifySampleResponse(self, response)

  def test_badRequest1(self):
    request = ""
    response = testUtils.symServerRequest(request, ip = "127.0.0.1",
      port = self.config['SymServer']['port'])
    self.assertEqual(response['code'], 400, "HTTP Status code should be 400")

  def test_badRequest2(self):
    request = "This is not JSON"
    response = testUtils.symServerRequest(request, ip = "127.0.0.1",
      port = self.config['SymServer']['port'])
    self.assertEqual(response['code'], 400, "HTTP Status code should be 400")

  def test_badRequest3(self):
    request = '{"stacks":[[[0,11723767],[1, 65802]]],'
    request +='"memoryMap":[["xul.pdb","44E4EC8C2F41492B9369D6B9A059577C2"],'
    request += '["wntdll.pdb","D74F79EB1F8D4A45ABCD2F476CCABACC2"]],'
    # No closing '}'
    request += '"version":4'
    response = testUtils.symServerRequest(request, ip = "127.0.0.1",
      port = self.config['SymServer']['port'])
    self.assertEqual(response['code'], 400, "HTTP Status code should be 400")

  def test_badRequest4(self):
    request = '{"stacks":[[[0,11723767],[1, 65802]]],'
    request +='"memoryMap":[["xul.pdb","44E4EC8C2F41492B9369D6B9A059577C2"],'
    # Memory map missing entries
    request += '],'
    request += '"version":4}'
    response = testUtils.symServerRequest(request, ip = "127.0.0.1",
      port = self.config['SymServer']['port'])
    self.assertEqual(response['code'], 400, "HTTP Status code should be 400")

  def test_badRequest5(self):
    request = '{"stacks":[[[0,11723767],[1, 65802]]],'
    request +='"memoryMap":[["xul.pdb","44E4EC8C2F41492B9369D6B9A059577C2"],'
    # Memory map missing entries
    request += '],'
    request += '"version":4}'
    response = testUtils.symServerRequest(request, ip = "127.0.0.1",
      port = self.config['SymServer']['port'])
    self.assertEqual(response['code'], 400, "HTTP Status code should be 400")

  def test_badRequest6(self):
    request = '{"stacks":[[[0,11723767],[1, 65802]]],'
    # Memory map missing altogether
    request += '"version":4}'
    response = testUtils.symServerRequest(request, ip = "127.0.0.1",
      port = self.config['SymServer']['port'])
    self.assertEqual(response['code'], 400, "HTTP Status code should be 400")

  def test_badRequest7(self):
    request = '{"stacks":[[[0,11723767],[1, 65802]]],'
    request +='"memoryMap":[["xul.pdb","44E4EC8C2F41492B9369D6B9A059577C2"],'
    request += '["wntdll.pdb","D74F79EB1F8D4A45ABCD2F476CCABACC2"]],'
    # No closing version
    request += '}'
    response = testUtils.symServerRequest(request, ip = "127.0.0.1",
      port = self.config['SymServer']['port'])
    self.assertEqual(response['code'], 400, "HTTP Status code should be 400")

  def test_badRequest8(self):
    # No stacks
    request = '{'
    request +='"memoryMap":[["xul.pdb","44E4EC8C2F41492B9369D6B9A059577C2"],'
    request += '["wntdll.pdb","D74F79EB1F8D4A45ABCD2F476CCABACC2"]],'
    request += '"version":4}'
    response = testUtils.symServerRequest(request, ip = "127.0.0.1",
      port = self.config['SymServer']['port'])
    self.assertEqual(response['code'], 400, "HTTP Status code should be 400")

if __name__ == '__main__':
  unittest.main()

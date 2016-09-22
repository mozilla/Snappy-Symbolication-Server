from logger import logger, logLevel
from validateRequest import validateRequest
from SymServer_Symbolicator import symbolicator

import json
import uuid
import tornado.web
import sys
import traceback

class RequestHandler(tornado.web.RequestHandler):
  def prepare(self):
    xForwardIp = self.request.headers.get("X-Forwarded-For")
    self.remoteIP = self.request.remote_ip if not xForwardIp else xForwardIp
    self.requestId = uuid.uuid4()

  def log(self, level, message):
    logger.log(level, "{} {}".format(self.requestId, message),
      remoteIP = self.remoteIP)

  def sendHeaders(self, code):
    self.set_status(code)
    self.set_header("Content-type", "application/json")

  def head(self):
    uri = self.request.uri
    self.log(logLevel.INFO, "Cannot process HEAD request: {}".format(uri))
    self.sendHeaders(405)

  def get(self):
    uri = self.request.uri
    self.log(logLevel.INFO, "Cannot process GET request: {}".format(uri))
    self.sendHeaders(405)

  def delete(self):
    uri = self.request.uri
    self.log(logLevel.INFO, "Cannot process DELETE request: {}".format(uri))
    self.sendHeaders(405)

  def patch(self):
    uri = self.request.uri
    self.log(logLevel.INFO, "Cannot process PATCH request: {}".format(uri))
    self.sendHeaders(405)

  def put(self):
    uri = self.request.uri
    self.log(logLevel.INFO, "Cannot process PUT request: {}".format(uri))
    self.sendHeaders(405)

  @tornado.gen.coroutine
  def post(self):
    uri = self.request.uri
    
    self.log(logLevel.INFO, "Processing POST request: {}".format(uri))

    try:
      requestBody = self.request.body
      self.log(logLevel.DEBUG, "Request body: {}".format(requestBody))

      requestBody = validateRequest(self.request.remote_ip, requestBody,
                                    self.log)
      if not requestBody:
        self.log(logLevel.ERROR, "Unable to validate request body")
        self.sendHeaders(400)
        return

      response = yield symbolicator.symbolicate(requestBody, self.requestId)
      response = json.dumps(response)
    except Exception as e:
      ex_type, ex, tb = sys.exc_info()
      stack = traceback.extract_tb(tb)
      self.log(logLevel.ERROR, "Could not formulate response: {}: {} STACK: {}"
        .format(ex_type, e, stack))
      self.sendHeaders(400)
      return

    try:
      self.sendHeaders(200)
      self.log(logLevel.DEBUG, "Response: {}".format(response))
      self.write(response)
    except Exception as e:
      self.log(logLevel.ERROR, "Exception during response: {}".format(e))
      return

    self.log(logLevel.INFO, "Response sent")

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
        self.debugAllowed = (self.request.remote_ip == "127.0.0.1")

    def log(self, level, message):
        logger.log(level, "{} {}".format(self.requestId, message), remoteIP=self.remoteIP)

    def sendHeaders(self, code):
        self.set_status(code)
        self.set_header("Content-type", "application/json")

    def head(self, path):
        uri = self.request.uri
        self.log(logLevel.INFO, "Cannot process HEAD request: {}".format(uri))
        self.sendHeaders(405)

    @tornado.gen.coroutine
    def get(self, path):
        if path == "/__lbheartbeat__":
            self.sendHeaders(200)
            return
        elif path == "/__heartbeat__":
            # Translate this to a debug request, which the server already has a
            # mechanism for handling. Then feed it in as if it was a POST
            # request.
            self.debugAllowed = True
            self.request.body = r'{"debug": true, "action": "heartbeat"}'
            yield self.post(path)
            return
        # Fall through
        self.sendHeaders(404)

    def delete(self, path):
        uri = self.request.uri
        self.log(logLevel.INFO, "Cannot process DELETE request: {}".format(uri))
        self.sendHeaders(405)

    def patch(self, path):
        uri = self.request.uri
        self.log(logLevel.INFO, "Cannot process PATCH request: {}".format(uri))
        self.sendHeaders(405)

    def put(self, path):
        uri = self.request.uri
        self.log(logLevel.INFO, "Cannot process PUT request: {}".format(uri))
        self.sendHeaders(405)

    @tornado.gen.coroutine
    def post(self, path):
        uri = self.request.uri

        self.log(logLevel.INFO, "Processing POST request: {}".format(uri))

        try:
            requestBody = self.request.body
            self.log(logLevel.DEBUG, "Request body: {}".format(requestBody))

            requestBody = validateRequest(self.debugAllowed, requestBody,
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
            self.sendHeaders(500)
            return

        try:
            self.sendHeaders(200)
            self.log(logLevel.DEBUG, "Response: {}".format(response))
            self.write(response)
        except Exception as e:
            self.log(logLevel.ERROR, "Exception during response: {}".format(e))
            return

        self.log(logLevel.INFO, "Response sent")

from logger import logLevel

import json

def validateRequest(remoteIP, data, logger):
  try:
    request = json.loads(data)
  except ValueError:
    logger(logLevel.DEBUG, "Request is not valid JSON")
    return None

  if not isinstance(request, dict):
    logger(logLevel.DEBUG, "Requst is not an object")
    return None

  # Check if this is a debug request
  debugRequest = validateDebugRequest(remoteIP, request, logger)
  if debugRequest:
    return debugRequest

  if not "stacks" in request:
    logger(logLevel.DEBUG, "Request does not contain 'stacks'")
    return None
  if not "memoryMap" in request:
    logger(logLevel.DEBUG, "Request does not contain 'memoryMap'")
    return None
  if not "version" in request:
    logger(logLevel.DEBUG, "Request does not contain 'version'")
    return None

  version = request["version"]
  stacks = request["stacks"]
  memoryMap = request["memoryMap"]

  if version != 4 and version != 3:
    logger(logLevel.WARNING,
      "Server currently supports versions 3 and 4 only ({} requested)"
      .format(version))
    return None

  if not isinstance(memoryMap, list):
    logger(logLevel.DEBUG, "The request's memoryMap is not a list")
    return None
  for data in memoryMap:
    if not isinstance(data, list):
      logger(logLevel.DEBUG, "An element of the memoryMap is not a list")
      return None
    if len(data) != 2:
      logger(logLevel.DEBUG,
        "There are more than two members of the memoryMap element")
      return None
    if not isinstance(data[0], basestring):
      logger(logLevel.DEBUG,
        "The first element of the memoryMap element is not a string")
      return None
    if not isinstance(data[1], basestring):
      logger(logLevel.DEBUG,
        "The second element of the memoryMap element is not a string")
      return None

  moduleCount = len(memoryMap)

  if not isinstance(stacks, list):
    logger(logLevel.DEBUG, "The request's stacks are not a list")
    return None
  for stack in stacks:
    if not isinstance(stack, list):
      logger(logLevel.DEBUG, "One of the request's stacks is not a list")
      return None
    for frame in stack:
      if not isinstance(frame, list):
        logger(logLevel.DEBUG,
          "One of the request's stack frames is not a list")
        return None
      if len(frame) != 2:
        logger(logLevel.DEBUG,
          "There are more than two members of the stack frame")
        return None
      if not isinstance(frame[0], int):
        logger(logLevel.DEBUG,
          "A stack frame module index is not an integer")
        return None
      if frame[0] >= moduleCount:
        logger(logLevel.DEBUG,
          "A stack frame module index is out of range")
        return None
      if not isinstance(frame[1], int):
        logger(logLevel.DEBUG,
          "A stack frame offset is not an integer")
        return None

    return request

def validateDebugRequest(remoteIP, request, logger):
  # Validation for debug requests is a bit less strict, but MUST come from the
  # localhost
  if remoteIP != "127.0.0.1":
    return None

  if 'debug' not in request:
    return None

  if request['debug'] != True:
    return None

  if 'action' not in request:
    return None

  if not isinstance(request['action'], basestring):
    return None

  logger(logLevel.WARNING, "Received debug request")
  return request

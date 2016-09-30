# Updates a configuration with new values
def configUpdate(original, update):
  for key in update:
    if key not in original:
      raise KeyError("Attempt to update key {} which does not exist".format(key))
    if isinstance(original[key], dict):
      if not isinstance(update[key], dict):
        raise TypeError("Attempt to update key {} with a non dict type".format(key))
      configUpdate(original[key], update[key])
    elif isinstance(original[key], list):
      if not isinstance(update[key], list):
        raise TypeError("Attempt to update key {} with a non list type".format(key))
      original[key] = update[key]
    elif isinstance(original[key], int):
      original[key] = int(update[key])
    elif isinstance(original[key], float):
      original[key] = float(update[key])
    elif isinstance(original[key], basestring):
      if not isinstance(update[key], basestring):
        raise TypeError("Attempt to update key {} with a non string type".format(key))
      original[key] = update[key]

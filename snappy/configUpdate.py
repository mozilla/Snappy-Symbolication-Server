# Updates a configuration with new values
def configUpdate(original, update):
  for key in update:
    if (key in original and
        isinstance(original[key], dict) and
        isinstance(update[key], dict)):
      configUpdate(original[key], update[key])
    else:
      original[key] = update[key]

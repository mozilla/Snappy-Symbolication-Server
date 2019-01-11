Status
------

The Snappy software has been deprecated in favor of [Tecken](https://github.com/mozilla-services/tecken). Tecken is what runs the symbols server at [symbols.mozilla.org](https://symbols.mozilla.org/).

Please file any issues and pull requests there.


Introduction
------------

Provides a Web server for symbolicating Firefox stacks. It matches function offsets
to modules in memory and looks up the corresponding function names in
server-side symbol files in [Breakpad's .sym format](https://chromium.googlesource.com/breakpad/breakpad/+/master/docs/symbol_files.md).

This project is intended as a drop-in replacement for the old
[Snappy Symbolication Server](https://github.com/mozilla/Snappy-Symbolication-Server/tree/e38f3fdd7b49ab181a95bd76bbd3a5f4fea97276).

The canonical Mozilla instance of this server runs at `https://symbolapi.mozilla.org/`.

Quick Start without Docker
--------------------------

1. Install [Python 2.7](https://www.python.org/downloads/) and
   [pip](https://pip.pypa.io/en/stable/installing/) if they are not already
   installed. Pip must be version 8.0 or above. It can be upgraded using
   `pip install -U 'pip>=8'`.
2. Install dependencies: `pip install -r requirements.txt`. You may want to do
   this in a
   [virtual environment](http://docs.python-guide.org/en/latest/dev/virtualenvs/)
3. Install [memcached](http://www.memcached.org/downloads)
4. Copy/create a configuration file and set values appropriately. See
   [Configuration File](#configuration-file)
5. Run `python quickstart.py -c [configuration file]`

The server(s) can then be stopped with
`python quickstart.py -c [configuration file] --stop`.
This will only work if quickstart was used to start the server(s).

Quick Start with Docker
-----------------------

1. Install [Docker](https://docs.docker.com/engine/installation)
2. It may be necessary that your user be in the Docker group. This can be
   accomplished in Linux with `sudo usermod -aG docker $(whoami)`. You must log
   out for changes to take effect.
3. Install [Python 2.7](https://www.python.org/downloads/) and
   [pip](https://pip.pypa.io/en/stable/installing/) if they are not already
   installed. Pip must be version 8.0 or above. It can be upgraded using
   `pip install -U 'pip>=8'`.
4. Install dependencies: `pip install -r requirements.txt`. You may want to do
   this in a
   [virtual environment](http://docs.python-guide.org/en/latest/dev/virtualenvs/)
5. Copy/create a configuration file and set values appropriately. See
   [Configuration File](#configuration-file). To use Docker, it is important
   that the `quickstart.Docker.enable = true`.
6. Run `python quickstart.py -c [configuration file]`

Quickstart attempts to do some caching in order to recreate the image and
container only when necessary. The image will be built only once. The container
will be recreated any time that the passed configuration changes. You can
force a full rebuild with `python quickstart.py -c [configuration file] -R`.
A full rebuild should be done anytime that the code changes.

The docker container can be stopped with
`python quickstart.py -c [configuration file] --stop`.

DiskCache
---------

An LRU cache of symbolication files. On cache misses, the file is automatically
retrieved and added to the cache.

**Important:** The directory used for cache data (specified in the configuration
as `DiskCache.cachePath`) must be used only for cache data. When DiskCache
starts, it reads all files in the cache directory into the cache. If there is
anything else in the cache path, it eventually will be evicted from the cache
and deleted from the disk.

**Also Important:** Do not delete anything from the cache while the DiskCache is
running. Doing this will screw up the cache. If DiskCache files get deleted,
restart the DiskCache server.

SymServer communicates with the DiskCache with the same protocol used to
make requests of SymServer.

The DiskCache imposes a size limit specified by the configuration option
`DiskCache.maxSizeMB`. However, the size limit is not strictly observed. When a
file is added to the cache, it is saved to the cache directory BEFORE evicting
enough cache items to bring the cache back under its maximum size.

Symbol files can be fairly large. Currently xul.sym is 72MB. However, before
being saved to the disk, the symbol data is processed to remove unnecessary data
and format remaining data into a more easily searchable form. After processing
xul.sym, only 13MB of data remain. This allows the cache to contain many symbols
more than it would otherwise.

SymServer
---------

Utilizes two caches to quickly symbolicate stacks. The first cache is memcached.
Addresses not in memcached are requested from DiskCache, which will either
retrieve the symbols from the cache, or download the symbols, add them to the
cache, and return them.

Takes POST requests in JSON format. This is the standard symbolication request
for testing:

```
curl -d '{"stacks":[[[0,11723767],[1, 65802]]],"memoryMap":[["xul.pdb","44E4EC8C2F41492B9369D6B9A059577C2"],["wntdll.pdb","D74F79EB1F8D4A45ABCD2F476CCABACC2"]],"version":4}' 127.0.0.1:8080
```

The request body must be a JSON object with the following three properties:
* `version`: the version number of the request format as an integer. Currently `4`.
* `stacks`: an array of stack traces. Each stack trace is an array of frames. Each frame is an array of two elements: `[module_index, module_offset]`. `module_index` is an index into the array in the `memoryMap` property as an integer. `module_offset` is the offset of this frame's instruction pointer relative to the base memory address of the module in which the code is contained as an integer.
* `memoryMap`: an array of modules. Each module is an array of two strings: `[debug_file, debug_identifier]`. Fully describing these parameters is out of scope for this document, but they are the last two elements of the `MODULE` line of a symbol file, and they can be used to locate the matching symbol file.

And the corresponding response:

```
{"symbolicatedStacks": [["XREMain::XRE_mainRun() (in xul.pdb)", "KiUserCallbackDispatcher (in wntdll.pdb)"]], "knownModules": [true, true]}
```

The response body is a JSON object with the following two properties:
* `symbolicatedStacks`: an array of stack traces, matching the order of the entries of the `stacks` property in the request. Each stack trace is an array of strings containing the function name for this stack frame, if available.
* `knownModules`: an array of booleans matching the order of the entries of the `memoryMap` property in the request. Each entry will be `true` if symbols were found for this module, and `false` otherwise.


Note that while it is possible to run the SymServer without memcached, DiskCache
is required for SymServer to operate properly.

Quickstart
----------

The quickstart script is designed to make it easier to start several servers at
once. The script keeps track of running instances by keeping pidfiles in a
directory called "pids" in the same directory as the quickstart script.
**Note:** If a server is started in any way other than by quickstart, its
pidfile will not be written to the correct place and quickstart will assume that
the server is not running and may try to start it again.

Quickstart's behavior is controlled largely by the configuration file. The
configuration file must be passed to quickstart for it to start the servers. The
configuration file passed will then be used by the servers that it starts as
well. For more information about how to pass in a configuration file, use the
`--help` argument.

Note that although there is a memcached binary available for Windows, quickstart
does not support it because of differences in operation and command line
options.

**External Memcached:**

Perhaps you do not want quickstart to manage memcached. This is totally fine and
quickstart is happy to play nicely with already running instances of memcached
(or to run without memcached). Simply set these options in the configuration
file:

- `quickstart.memcached.start` should be set to `false`.
- `SymServer.memcachedServers` should be set to a list of memcached servers to
  use (or an empty list to operate without memcached).

More information on these options can be found in the
[Configuration File](#configuration-file) section.

Configuration File
------------------

The configuration file uses JSON format which can be passed in to DiskCache,
SymServer, and quickstart with the -c option.

Sensible default configuration options are provided. These are overridden by
anything in the passed configuration file. Options in the configuration file
are, in turn, overridden by any passed command line options. Use the `--help`
argument to learn more about command line options.

An example configuration file is included: `sample_config.json`.

All configuration values should be specified as strings unless otherwise noted.

**Configuration Values:**

- `"DiskCache"` Configuration relating to the DiskCache
    - `"cachePath"` The directory used for cache storage.

        **Important:** The directory used for cache storage must be used ONLY
        for cache data. When DiskCache starts, it reads all files in the cache
        directory into the cache. If there is anything else in the cache path,
        it eventually will be evicted from the cache and deleted.

    - `"localSymbolDirs"` A list of strings, each specifying a local directory
      of symbols. Typically symbol directories would be generated using
      `./mach buildsymbols` as described in
      [Profiling local builds (without using Talos)](https://developer.mozilla.org/en-US/docs/Mozilla/Performance/Profiling_with_the_Built-in_Profiler_and_Local_Symbols_on_Windows#Profiling_local_builds_%28without_using_talos%29).

        **Note:** When you regenerate a symbol directory, remember that
        memcached may still be caching old symbol values. To prevent this, you
        can restart memcached when you regenerate symbol directories or turn it
        off entirely by specifying an empty list for the
        `SymServer.memcachedServers` configuration option.

    - `"maxSizeMB"` The maximum size of the DiskCache in megabytes. Note that
      the cache may, at times, be larger than this. See [DiskCache](#diskcache)
      for details. This value must be an integer type.
    - `"port"` The port number to serve the DiskCache on. Must be an integer
      type.
    - `"retries"` Must be an integer type. Sets the maximum number of retries
      that will be attempted before giving up.
    - `"retryDelayMs"` Must be an integer type. Sets the approximate amount of
      delay between retries.
    - `"symbolURLs"` A list of strings, each specifying a URL from which symbols
      can be requested. Symbol files will be requested from each URL at
      `<url>/<module>/<breakpadId>/<symbol filename>`.

        Each URL on the list will be tried, in order, until one returns a
        response with a HTTP 200 status code.

    - `"log"` Configuration of DiskCache logging
        - `"path"` Path to save the log to
        - `"level"` Threshold for this DiskCache logger. Logging messages that
          are less severe than the given level will be ignored. Level must be an
          integer type. Level values correspond to those used by the
          [Python logger module](https://docs.python.org/2/library/logging.html#levels).
        - `"maxFiles"` An integer type describing how many files to use when
          rotating the logs.
        - `"maxFileSizeMB"` An integer type describing how large logs can get
          (in megabytes) before being rotated.
- `"SymServer"` Configuration relating to the symbolication server
    - `"port"` The port number to serve the symbolication server on. Must be an
      integer type.
    - `"memcachedServers"` A list of strings, each denoting an address
      (including port number) of a memcached server. If the list is empty,
      memcached will not be used.
    - `"DiskCacheServer"` A single string specifying the address (including
      port number) of the DiskCache server to use
    - `"log"` Configuration of SymServer logging
        - `"path"` Path to save the log to
        - `"level"` Threshold for this SymServer logger. Logging messages that
          are less severe than the given level will be ignored. Level must be an
          integer type. Level values correspond to those used by the
          [Python logger module](https://docs.python.org/2/library/logging.html#levels).
        - `"maxFiles"` An integer type describing how many files to use when
          rotating the logs.
        - `"maxFileSizeMB"` An integer type describing how large logs can get
          (in megabytes) before being rotated.
- `"quickstart"` Configuration options related to the quickstart script
    - `"verbose"` Must be a boolean type. If set to `true`, quickstart will
      display additional output. Useful for debugging. Setting this to `true`
      is equivilant to passing `--verbose` to the quickstart script.
    - `"Docker"` Configuration options related to Docker
        - `"enable"` Must be a boolean type. If set to `true`, quickstart
          will start the servers within a Docker container
        - `"publish"`
            - `"memcached"` Must be a boolean type. If set to `true`, the port
              that memcached is running on will be exposed to the host system.
              If set to `false`, memcached will be accessible only from within
              the Docker container.
            - `"DiskCache"` Must be a boolean type. If set to `true`, the port
              that DiskCache is running on will be exposed to the host system.
              If set to `false`, DiskCache will be accessible only from within
              the Docker container.
            - `"SymServer"` Must be a boolean type. If set to `true`, the port
              that SymServer is running on will be exposed to the host system.
              If set to `false`, SymServer will be accessible only from within
              the Docker container
        - `"apiSocket"` The socket where the
          [Docker API](https://docs.docker.com/engine/reference/api/docker_remote_api/)
          is available.
    - `"memcached"` Configuration options related to how memcached is run
      by quickstart. **Note:** this has no effect on starting memcached in other
      ways.
        - `"start"` Must be a boolean type. If set to `false`, memcached will
          not be started by quickstart.
        - `"restart"` Must be a boolean type. If set to `false`, memcached will
          not be started by quickstart if it is already running. If set to
          `true`, quickstart will stop the existing memcached process and start
          a new one.
        - `"binary"` The command to run to start memcached. Must not include
          any arguments. If memcached is in your PATH, it is likely sufficient
          for this option to be set to the string "memcached". Otherwise the
          path to the memcached binary should be specified.
        - `"port"` Port for memcached to listen on. Must be an integer type.
        - `"listenAddress"` The address for memcached to listen on.
        - `"maxMemoryMB"` The maximum amount of memory memcached should use, in
          megabytes
    - `"DiskCache"` Configuration options related to how DiskCache is run by the
      quickstart script.
        - `"start"` Must be a boolean type. If set to `false`, DiskCache will
          not be started by quickstart.
        - `"restart"` Must be a boolean type. If set to `false`, DiskCache will
          not be started by quickstart if it is already running. If set to
          `true`, quickstart will stop the existing DiskCache process and start
          a new one.
    - `"SymServer"` Configuration options related to how SymServer is run by the
      quickstart script.
        - `"start"` Must be a boolean type. If set to `false`, SymServer will
          not be started by quickstart.
        - `"restart"` Must be a boolean type. If set to `false`, SymServer will
          not be started by quickstart if it is already running. If set to
          `true`, quickstart will stop the existing SymServer process and start
          a new one.

Troubleshooting
---------------

If you are having problems getting the server started, there are some steps you
can try. First try checking the DiskCache and SymServer logs. By default they
are located at DiskCache.log and SymServer.log respectively. If there are no
clues there, try starting the servers without the quickstart script. Currently,
the quickstart script does very little in terms of checking that the servers
started properly.

1. Start memcached. These arguments may be useful.
    * `-d` Run as a daemon
    * `-U` Port to use for UDP connections. quickstart sets this to 0 to disable
      UDP connections.
    * `-p` Port to use for TCP connections. Defaults to 11211.
    * `-l` Address to listen on.
    * `-m` Maximum memory usage of the cache in megabytes
    * `-P` Write PID to the specified pidfile. Only valid when combined with
      `-d`. quickstart sets this to "pids/memcached.pid"
2. Start DiskCache with `python snappy/DiskCache.py -c [config]`
3. Start SymServer with `python snappy/SymServer.py -c [config]`
4. Try using curl to send a test request as described in
   [SymServer](#symserver).

Tests
-----

The Symbolication Server includes its own tests. There are two options for
running tests. `python runTests.py` runs all tests.
`python tests/test_[name].py` runs just one test. These test scripts expect to
be able to start Snappy using quickstart without Docker, so be sure to follow
the setup instructions listed in
[Quick Start without Docker](#quick-start-without-docker).

There is also the capability to use a certain configuration for testing. This is
done by passing a configuration file to the runTests script with
`python runTests.py -c [path]`. Doing this copies the configuration file to a
specific location in the test directory, allowing tests to read the
configuration from it, if it exists. Because the configuration is copied, it is
persistant to a certain degree. When using the runTests script, any existing
configuration file is deleted before the tests are run unless runTests is called
with the `-o`/`--oldConfig` option. When running individual tests however,
there is no option to pass a configuration file. To provide configuration when
running individual tests, use `python runTests.py -c [path] --noRun` or
`python runTests.py -nc [path]` to properly set up individual tests to use the
specified configuration. If no configuration is provided, all default values
will be used.

Some configuration options are overridden in order for testing to work properly.
Temporary directories are used for the DiskCache and log files. Local symbol
directories are ignored. All servers have their quickstart 'start' and 'restart'
options set to `true`. The SymServer's configuration is overridden to force it
to use only the locally started DiskCache and memcached servers.

Note that testing currently requires memcached to run locally, which means that
it is not supported on Windows.

**Important:** These tests should not be run on a production machine that is
already running SymServer, DiskCache or memcached. The tests attempt to stop
any currently running servers so that test servers can be started.

If you are seeing failures because the servers cannot be started, check to see
if they were already started without quickstart. If they were, quickstart cannot
stop them (because it doesn't know what processes they are). When quickstart
attempts to start the already running servers, they likely fail when attempting
to bind to the same port that the running server is already using.

Debug Protocol
--------------

SymServer and DiskCache have a special debugging protocol. This protocol
can only be used via POST requests that originate from the localhost. Like the
standard communication protocol, this one accepts JSON via POST data. This
protocol is used by some test scripts in order to allow for testing things like
cache hits and misses. All requests using the debug protocol must contain
(within the request JSON) the property `"debug": true`. This command is an
example of how a debug request can be sent:

```
curl -d '{"debug": true, "action": "outputCacheHits", "enabled": true}' 127.0.0.1:8080
```

Debug requests must have an `"action"` property with a string value. This
property describes what the debug request does.

**DiskCache debug actions:**

- `"cacheAddRaw"` Evicts any matching cache file and downloads it again, saving
  it byte for byte as it was received. This prevents regular file processing
  which normally lowers the space needed per cache file and decreases lookup
  times.
    - Required properties:
        - `"libName"` The name of the library (ex: "xul.pdb").
        - `"breakpadId"` The breakpad ID
          (ex: "44E4EC8C2F41492B9369D6B9A059577C2").
    - Response properties:
        - `"path"` The path of the resulting cache file. If the file could not
          be downloaded and added to the cache, `null` is returned instead.
- `"cacheGet"` Gets the file from the cache. If it is not in the cache, it is
  downloaded and added.
    - Required properties:
        - `"libName"` The name of the library (ex: "xul.pdb").
        - `"breakpadId"` The breakpad ID
          (ex: "44E4EC8C2F41492B9369D6B9A059577C2").
    - Response properties:
        - `"path"` The path of the resulting cache file. If the file could not
          be downloaded and added to the cache, `null` is returned instead.
- `"cacheEvict"` Removes the file from the cache.
    - Required properties:
        - `"libName"` The name of the library (ex: "xul.pdb").
        - `"breakpadId"` The breakpad ID
          (ex: "44E4EC8C2F41492B9369D6B9A059577C2").
    - Response properties:
        - `"success"` Will be set to `true` if cache now does not contain the
          file.
- `"cacheExists"` Checks if the file is in the cache.
    - Required properties:
        - `"libName"` The name of the library (ex: "xul.pdb").
        - `"breakpadId"` The breakpad ID
          (ex: "44E4EC8C2F41492B9369D6B9A059577C2").
    - Response properties:
        - `"exists"` Will be set to `true` if cache contains the file.

**SymServer debug actions:**

- `"outputCacheHits"` Toggles mode wherein standard (non-debug) requests get an
  additional response property: `"cacheHits"`. It will be structured much like
  the `"symbolicatedStacks"` property: A list of lists of booleans. Each sublist
  represents a stack and each boolean represents whether that frame in the stack
  was in the cache.
    - Required properties:
        - `"enabled"` If `true`, outputCacheHits mode is turned on. If `false`,
          it is turned off.
    - Response properties:
        - `"success"` Will be set to `true` if the mode change was successful.
- `"cacheEvict"` Evicts an item from the cache.
    - Required properties:
        - `"libName"` The name of the library (ex: "xul.pdb").
        - `"breakpadId"` The breakpad ID
          (ex: "44E4EC8C2F41492B9369D6B9A059577C2").
        - `"offset"` The offset of the frame (ex: "11723767")
    - Response properties:
        - `"success"` Will be set to `true` if cache now does not contain the
          cache entry.

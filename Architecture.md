The symbolication server consists of three microservices: SymServer, DiskCache,
and memcached. memcached is an external service with documentation that can be
found at [memcached.org](http://www.memcached.org/).

SymServer
---------

**Configuration:**

SymServer requires configuration data to start. It takes this data via a
command line option, either in the form of a JSON file, or as a literal JSON
argument. It passes this data to its configuration module, `SymServer_Config`.

This module defines a `Config` class and a `config` instance of the class.
Typically, the instance should be used (rather than the class). This allows all
modules that import the configuration module to import the same exact
configuration. The notable exception is `testUtils.getDefaultConfig`. This
function is called many times during testing, and needs to get a new instance
of the configuration each time.

The `config` object is simply a dictionary that loads default values and
provides methods to load data from configuration input sources.

**Request Handling:**

SymServer handles requests with [Tornado](http://www.tornadoweb.org). It sets
up a single request handler to handle all incoming requests. The request
handler module is `SymServer_RequestHandler`. The request handler rejects
everything but POST requests.

The POST handler uses the `@tornado.gen.coroutine` decorator which allows the
handler to yield a Future, then resume execution once the Future has been
resolved. This means that although Python is forced to run as a single process
(due to the global interpreter lock), it can handle simultaneous requests.

The POST handler validates the response, then yields on the result of
symbolication from `SymServer_Symbolicator.symbolicator.symbolicate`. This
validation is provided by the `validateRequest` module and is identical
for the SymServer and the DiskCache since they both use the same standard
protocol. There are some differences in the debug protocol, which are not
checked. The validation of debug requests largly consists of ensuring that the
source of the request is the localhost. It is assumed that no malicious or
otherwise problematic requests will originate from localhost.

**Symbolication:**

The symbolication happens in the `SymServer_Symbolicator` module. The requests
to do so are handled by `SymServer_Symbolicator.symbolicator.symbolicate`.
Certain types of debug requests are handled directly by this function. For
other requests, a `SymbolicationThread` thread is started to perform
symbolication. The thread is passed the request to symbolicate and a Future that
is then returned by the `symbolicate()` function to the request handler.

The `SymbolicationThread` starts by making a request template and populating it
with the values that it will return if none of the symbols can be resolved. It
then makes a bare "subrequest" that it will issue to the DiskCache to resolve
frames that are not in memcached. It then iterates over the frames and queries
memcached for each one. On cache hits, the result is inserted into the response
object. On cache misses, the frame is inserted into the subrequest. After all
frames have been processed, if there are no unresolved frames in the subrequest
then it is done. Otherwise the subrequest is sent to the DiskCache. The
DiskCache is expected to resolve any symbols possible from its cache, then
retrieve other symbol files to resolve remaining symbols. Once the response is
received, the symbolicated frames are extracted and inserted into both the
response object and memcached. Lastly, the Future is resolved with the
response object, allowing the request handler to resume execution and send
the response.

DiskCache
---------

The DiskCache's Configuration and Request Handling work almost identically to
how the SymServer's do.

**Symbolication:**

Like `SymServer_Symbolicator.symbolicator.symbolicate`,
`DiskCache_DiskCache.diskCache.request` is called by the request handler and
returns a future to it. Also similarly to with SymServer, a thread is used to
perform the work needed and resolve the future. Unlike SymServer, however,
DiskCache only runs a single worker thread rather than running a new one for
each request. The reasoning for this is that SymServer spends time waiting
for network responses during it's threads' actifity. There is no reason why
SymServer cannot submit more requests to memcached and DiskCache while it is
waiting for responses to its previous requests. DiskCache, on the other hand,
spends its time reading large files from the network and the disk. Attempting
to read multiple at once will not significantly increase speeds since the
limiting factor for both is the amount of bandwidth.

Therefore, rather than starting up a new `DiskCacheThread`, `request()` simply
uses a `Queue.Queue` to send the existing one the new request, response
template, and Future. Then `request()` returns the Future to the request
handler.

Meanwhile, the `DiskCacheThread` (assuming it is not already processing a
request) is blocking on getting an item from the queue. Once there is an item in
the queue for it to retrieve, it copies it (and anything else in the queue) into
it's own list-based queue. The reason for having two queues is that
`Queue.Queue` provides convenient and safe methods for transferring data from
thread to thread, but does not allow for access to elements of the queue that
are not at the head (which DiskCache needs).

Once there are items in DiskCache's queue, it iterates over the *modules*
(not frames) in the request. For each module, it finds all frames in *all*
requests in the queue that use that exact module. It then looks up whether
that module is available locally. If necessary, the module's symbol file is
downloaded and saved to the cache. Then the file is read and all possible
symbols resolved. The resolved symbols are then inserted in to all response
objects for the modules that were located. Once all modules in the request
have been symbolicated, the Future for that requests is resolved with the
response object so that it can be sent by the request handler.

**Saving Symbol Files:**

Rather than saving raw symbol files, unused data is first removed and the data
is sorted. This allows for less space consumed and faster lookup speeds. This
is done by reading lines that start with "PUBLIC" or "FUNC". Those lines are
split to obtain the address and symbol. Then the list of addresses is sorted
in decending order and just the addresses and their symbols are written to the
file. The first line of the file is given a special value that allows these
stripped symbol files to be easily distinguished from raw ones.

**Reading Symbol Files:**

The first line of the file is read to determine if the file is a raw or
stripped symbol file. If it is a raw symbol file, it is simply necessary to read
the file's lines in order and, for each symbol we are looking for, stop when we
encounter an address less than or equal to it.

We need to handle raw symbol files for two reasons: local symbol files will be
raw and debug requests can specify that a symbol file should be saved raw. To
read raw symbol files, we read lines one at a time looking for "PUBLIC" and
"FUNC" lines. When one is found, the address and symbol are split, then the
address is compared to each of the addresses we are looking for. For each of
the address we are looking for, we keep track of the closest address found that
is less than or equal to the address desired. After reading the whole file,
the closest addresses found are returned.

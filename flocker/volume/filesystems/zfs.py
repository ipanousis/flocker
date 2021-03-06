# Copyright Hybrid Logic Ltd.  See LICENSE file for details.

"""
ZFS APIs.
"""

from __future__ import absolute_import

import os
from contextlib import contextmanager
from uuid import uuid4
from subprocess import (
    CalledProcessError, STDOUT, PIPE, Popen, check_call, check_output
)

from characteristic import attributes, with_cmp, with_repr

from zope.interface import implementer

from eliot import Field, MessageType, Logger

from twisted.python.filepath import FilePath
from twisted.internet.endpoints import ProcessEndpoint, connectProtocol
from twisted.internet.protocol import Protocol
from twisted.internet.defer import Deferred, succeed
from twisted.internet.error import ConnectionDone, ProcessTerminated
from twisted.application.service import Service

from .interfaces import (
    IFilesystemSnapshots, IStoragePool, IFilesystem,
    FilesystemAlreadyExists)


def random_name():
    """Return a random pool name.

    :return: Random ``bytes``.
    """
    return os.urandom(8).encode("hex")


class CommandFailed(Exception):
    """The ``zfs`` command failed for some reasons."""


class BadArguments(Exception):
    """The ``zfs`` command was called with incorrect arguments."""


class _AccumulatingProtocol(Protocol):
    """
    Accumulate all received bytes.
    """

    def __init__(self):
        self._result = Deferred()
        self._data = b""

    def dataReceived(self, data):
        self._data += data

    def connectionLost(self, reason):
        if reason.check(ConnectionDone):
            self._result.callback(self._data)
        elif reason.check(ProcessTerminated) and reason.value.exitCode == 1:
            self._result.errback(CommandFailed())
        elif reason.check(ProcessTerminated) and reason.value.exitCode == 2:
            self._result.errback(BadArguments())
        else:
            self._result.errback(reason)
        del self._result


def zfs_command(reactor, arguments):
    """
    Asynchronously run the ``zfs`` command-line tool with the given arguments.

    :param reactor: A ``IReactorProcess`` provider.

    :param arguments: A ``list`` of ``bytes``, command-line arguments to
    ``zfs``.

    :return: A :class:`Deferred` firing with the bytes of the result (on
        exit code 0), or errbacking with :class:`CommandFailed` or
        :class:`BadArguments` depending on the exit code (1 or 2).
    """
    endpoint = ProcessEndpoint(reactor, b"zfs", [b"zfs"] + arguments,
                               os.environ)
    d = connectProtocol(endpoint, _AccumulatingProtocol())
    d.addCallback(lambda protocol: protocol._result)
    return d


_ZFS_COMMAND = Field.forTypes(
    "zfs_command", [bytes], u"The command which was run.")
_OUTPUT = Field.forTypes(
    "output", [bytes], u"The output generated by the command.")
_STATUS = Field.forTypes(
    "status", [int], u"The exit status of the command")


ZFS_ERROR = MessageType(
    "filesystem:zfs:error", [_ZFS_COMMAND, _OUTPUT, _STATUS],
    u"The zfs command signaled an error.")


def _sync_command_error_squashed(arguments, logger):
    """
    Synchronously run a command-line tool with the given arguments.

    :param arguments: A ``list`` of ``bytes``, command-line arguments to
        execute.

    :param eliot.Logger logger: The log writer to use to log errors running the
        zfs command.
    """
    message = None
    log_arguments = b" ".join(arguments)
    try:
        process = Popen(arguments, stdout=PIPE, stderr=STDOUT)
        output = process.stdout.read()
        status = process.wait()
    except Exception as e:
        message = ZFS_ERROR(
            zfs_command=log_arguments, output=str(e), status=1)
    else:
        if status:
            message = ZFS_ERROR(
                zfs_command=log_arguments, output=output, status=status)
    if message is not None:
        message.write(logger)


@attributes(["name"])
class Snapshot(object):
    """
    A snapshot of a ZFS filesystem.

    :ivar bytes name: The name of the snapshot.
    """
    # TODO: The name should probably be a structured object of some sort,
    # not just a wrapper for bytes.
    # https://github.com/ClusterHQ/flocker/issues/668


def _latest_common_snapshot(some, others):
    """
    Pick the most recent snapshot that is common to two snapshot lists.

    :param list some: One ``list`` of ``Snapshot`` instances to consider,
        ordered from oldest to newest.

    :param list others: Another ``list`` of ``Snapshot`` instances to consider,
        ordered from oldest to newest.

    :return: The ``Snapshot`` instance which occurs closest to the end of both
        ``some`` and ``others`` If no ``Snapshot`` appears in both, ``None`` is
        returned.
    """
    others_set = set(others)
    for snapshot in reversed(some):
        if snapshot in others_set:
            return snapshot
    return None


@implementer(IFilesystem)
@with_cmp(["pool", "dataset"])
@with_repr(["pool", "dataset"])
class Filesystem(object):
    """A ZFS filesystem.

    For now the goal is simply not to pass bytes around when referring to a
    filesystem.  This will likely grow into a more sophisticiated
    implementation over time.
    """
    def __init__(self, pool, dataset, mountpoint=None, reactor=None):
        """
        :param pool: The filesystem's pool name, e.g. ``b"hpool"``.

        :param dataset: The filesystem's dataset name, e.g. ``b"myfs"``, or
            ``None`` for the top-level filesystem.

        :param twisted.python.filepath.FilePath mountpoint: Where the
            filesystem is mounted.
        """
        self.pool = pool
        self.dataset = dataset
        self._mountpoint = mountpoint
        if reactor is None:
            from twisted.internet import reactor
        self._reactor = reactor

    def _exists(self):
        """
        Determine whether this filesystem exists locally.

        :return: ``True`` if there is a filesystem with this name, ``False``
            otherwise.
        """
        try:
            check_output([b"zfs", b"list", self.name], stderr=STDOUT)
        except CalledProcessError:
            return False
        return True

    def snapshots(self):
        if self._exists():
            zfs_snapshots = ZFSSnapshots(self._reactor, self)
            d = zfs_snapshots.list()
            d.addCallback(lambda snapshots:
                          [Snapshot(name=name)
                           for name in snapshots])
            return d
        return succeed([])

    @property
    def name(self):
        """The filesystem's full name, e.g. ``b"hpool/myfs"``."""
        if self.dataset is None:
            return self.pool
        return b"%s/%s" % (self.pool, self.dataset)

    def get_path(self):
        return self._mountpoint

    @contextmanager
    def reader(self, remote_snapshots=None):
        """
        Send zfs stream of contents.

        :param list remote_snapshots: ``Snapshot`` instances, ordered from
            oldest to newest, which are available on the writer.  The reader
            may generate a partial stream which relies on one of these
            snapshots in order to minimize the data to be transferred.
        """
        # The existing snapshot code uses Twisted, so we're not using it
        # in this iteration.  What's worse, though, is that it's not clear
        # if the current snapshot naming scheme makes any sense, and
        # moreover it violates abstraction boundaries. So as first pass
        # I'm just using UUIDs, and hopefully requirements will become
        # clearer as we iterate.
        snapshot = b"%s@%s" % (self.name, uuid4())
        check_call([b"zfs", b"snapshot", snapshot])

        # Determine whether there is a shared snapshot which can be used as the
        # basis for an incremental send.
        local_snapshots = list(
            Snapshot(name=name) for name in
            _parse_snapshots(
                check_output([b"zfs"] + _list_snapshots_command(self)),
                self
            ))

        if remote_snapshots is None:
            remote_snapshots = []

        latest_common_snapshot = _latest_common_snapshot(
            remote_snapshots, local_snapshots)

        if latest_common_snapshot is None:
            identifier = [snapshot]
        else:
            identifier = [
                b"-i",
                u"{}@{}".format(
                    self.name, latest_common_snapshot.name).encode("ascii"),
                snapshot,
            ]

        process = Popen([b"zfs", b"send"] + identifier, stdout=PIPE)
        try:
            yield process.stdout
        finally:
            process.stdout.close()
            process.wait()

    @contextmanager
    def writer(self):
        """
        Read in zfs stream.
        """
        if self._exists():
            # If the filesystem already exists then this should be an
            # incremental data stream to up date it to a more recent snapshot.
            # If that's not the case then we're about to screw up - but that's
            # all we can handle for now.  Using existence of the filesystem to
            # determine whether the stream is incremental or not is definitely
            # a hack.  When we replace this mechanism with a proper API we
            # should make it include that information.
            #
            # -e means "if the stream says it is for foo/bar/baz then receive
            # into baz".  I don't know why self.name is also required,
            # then. XXX try -d self.pool instead. XXX it works without -e w/
            # self.name too. XXX Delete this paragraph if we go ahead with just
            # `-F` in the implementation.
            #
            # -F means force.  If the stream is based on not-quite-the-latest
            # snapshot then we have to throw away all the snapshots newer than
            # it in order to receive the stream.  To do that you have to
            # force.
            #
            cmd = [b"zfs", b"receive", b"-F", self.name]
        else:
            # If the filesystem doesn't already exist then this is a complete
            # data stream.
            cmd = [b"zfs", b"receive", self.name]
        process = Popen(cmd, stdin=PIPE)
        succeeded = False
        try:
            yield process.stdin
        finally:
            process.stdin.close()
            succeeded = not process.wait()
        if succeeded:
            check_call([b"zfs", b"set",
                        b"mountpoint=" + self._mountpoint.path,
                        self.name])


@implementer(IFilesystemSnapshots)
class ZFSSnapshots(object):
    """Manage snapshots on a ZFS filesystem."""

    def __init__(self, reactor, filesystem):
        self._reactor = reactor
        self._filesystem = filesystem

    def create(self, name):
        encoded_name = b"%s@%s" % (self._filesystem.name, name)
        d = zfs_command(self._reactor, [b"snapshot", encoded_name])
        d.addCallback(lambda _: None)
        return d

    def list(self):
        """
        List ZFS snapshots known to the volume manager.
        """
        return _list_snapshots(self._reactor, self._filesystem)


def _list_snapshots_command(filesystem):
    """
    Construct a ``zfs`` command which will output the names of the snapshots of
    the given filesystem.

    :param Filesystem filesystem: The ZFS filesystem the snapshots of which to
        list.

    :return list: An argument list (of ``bytes``) which can be passed to
        ``zfs`` to produce the desired list of snapshots.  ``zfs`` is not
        included as the first element.
    """
    return [
        b"list",
        # Format the output without a header.
        b"-H",
        # Recurse to datasets beneath the named dataset.
        b"-r",
        # Only output datasets of type snapshot.
        b"-t", b"snapshot",
        # Only output the name of each dataset encountered.  The name is the
        # only thing we currently store in our snapshot model.
        b"-o", b"name",
        # Sort by the creation property.  This gives us the snapshots in the
        # order they were taken.
        b"-s", b"creation",
        # Start with this the dataset we're interested in.
        filesystem.name,
    ]


def _parse_snapshots(data, filesystem):
    """
    Parse the output of a ``zfs list`` command (like the one defined by
    ``_list_snapshots_command`` into a ``list`` of ``bytes`` (the snapshot
    names only).

    :param bytes data: The output to parse.

    :param Filesystem filesystem: The filesystem from which to extract
        snapshots.  If the output includes snapshots for other filesystems (eg
        siblings or children) they are excluded from the result.

    :return list: A ``list`` of ``bytes`` corresponding to the
        names of the snapshots in the output.  The order of the list is the
        same as the order of the snapshots in the data being parsed.
    """
    result = []
    for line in data.splitlines():
        dataset, snapshot = line.split(b'@', 1)
        if dataset == filesystem.name:
            result.append(snapshot)
    return result


def _list_snapshots(reactor, filesystem):
    """
    List the snapshots of the given filesystem.

    :param IReactorProcess reactor: The reactor to use to launch the ``zfs``
        child process.

    :param Filesystem filesystem: The filesystem the snapshots of which to
        retrieve.

    :return: A ``Deferred`` which fires with a ``list`` of ``Snapshot``
        instances giving the requested snapshot information.
    """
    d = zfs_command(reactor, _list_snapshots_command(filesystem))
    d.addCallback(_parse_snapshots, filesystem)
    return d


def volume_to_dataset(volume):
    """Convert a volume to a dataset name.

    :param flocker.volume.service.Volume volume: The volume.

    :return: Dataset name as ``bytes``.
    """
    return b"%s.%s" % (volume.uuid.encode("ascii"),
                       volume.name.to_bytes())


@implementer(IStoragePool)
@with_repr(["_name"])
@with_cmp(["_name", "_mount_root"])
class StoragePool(Service):
    """
    A ZFS storage pool.

    Remotely owned filesystems are mounted read-only to prevent changes
    (divergence which would break ``zfs recv``).  This is done by having the
    root dataset be ``readonly=on`` - which is inherited by all child datasets.
    Locally owned datasets have this overridden with an explicit
    ```readonly=off`` property set on them.
    """
    logger = Logger()

    def __init__(self, reactor, name, mount_root):
        """
        :param reactor: A ``IReactorProcess`` provider.
        :param bytes name: The pool's name.
        :param FilePath mount_root: Directory where filesystems should be
            mounted.
        """
        self._reactor = reactor
        self._name = name
        self._mount_root = mount_root

    def startService(self):
        """
        Make sure that the necessary properties are set on the root Flocker zfs
        storage pool.
        """
        Service.startService(self)

        # These next things are logically part of the storage pool creation
        # process.  Since Flocker itself doesn't yet have any involvement with
        # that process, it's difficult to find a better time/place to set these
        # properties than here - ie, "every time we're about to interact with
        # the storage pool".  In the future it would be better if we could do
        # these things one-off - sometime around when the pool is created or
        # when Flocker is first installed, for example.  Then we could get rid
        # of these operations from this method (which eliminates the motivation
        # for StoragePool being an IService implementation).
        # https://github.com/ClusterHQ/flocker/issues/635

        # Set the root dataset to be read only; IService.startService
        # doesn't support Deferred results, and in any case startup can be
        # synchronous with no ill effects.
        _sync_command_error_squashed(
            [b"zfs", b"set", b"readonly=on", self._name], self.logger)

        # If the root dataset is read-only then it's not possible to create
        # mountpoints in it for its child datasets.  Avoid mounting it to avoid
        # this problem.  This should be fine since we don't ever intend to put
        # any actual data into the root dataset.
        _sync_command_error_squashed(
            [b"zfs", b"set", b"canmount=off", self._name], self.logger)

    def create(self, volume):
        filesystem = self.get(volume)
        mount_path = filesystem.get_path().path
        properties = [b"-o", b"mountpoint=" + mount_path]
        if volume.locally_owned():
            properties.extend([b"-o", b"readonly=off"])
        d = zfs_command(self._reactor,
                        [b"create"] + properties + [filesystem.name])
        d.addCallback(lambda _: filesystem)
        return d

    def clone_to(self, parent, volume):
        parent_filesystem = self.get(parent)
        new_filesystem = self.get(volume)
        zfs_snapshots = ZFSSnapshots(self._reactor, parent_filesystem)
        snapshot_name = bytes(uuid4())
        d = zfs_snapshots.create(snapshot_name)
        clone_command = [b"clone",
                         # Snapshot we're cloning from:
                         b"%s@%s" % (parent_filesystem.name, snapshot_name),
                         # New filesystem we're cloning to:
                         new_filesystem.name,
                         ]
        d.addCallback(lambda _: zfs_command(self._reactor, clone_command))
        self._created(d, volume)
        d.addCallback(lambda _: new_filesystem)
        return d

    def change_owner(self, volume, new_volume):
        old_filesystem = self.get(volume)
        new_filesystem = self.get(new_volume)
        d = zfs_command(self._reactor,
                        [b"rename", old_filesystem.name, new_filesystem.name])
        self._created(d, new_volume)

        def remounted(ignored):
            # Use os.rmdir instead of FilePath.remove since we don't want
            # recursive behavior. If the directory is non-empty, something
            # went wrong (or there is a race) and we don't want to lose data.
            os.rmdir(old_filesystem.get_path().path)
        d.addCallback(remounted)
        d.addCallback(lambda _: new_filesystem)
        return d

    def _created(self, result, new_volume):
        """
        Common post-processing for attempts at creating new volumes from other
        volumes.

        In particular this includes error handling and ensuring read-only
        and mountpoint properties are set correctly.

        :param Deferred result: The result of the creation attempt.

        :param Volume new_volume: Volume we're trying to create.
        """
        new_filesystem = self.get(new_volume)
        new_mount_path = new_filesystem.get_path().path

        def creation_failed(f):
            if f.check(CommandFailed):
                # This isn't the only reason the operation could fail. We
                # should figure out why and report it appropriately.
                # https://github.com/ClusterHQ/flocker/issues/199
                raise FilesystemAlreadyExists()
            return f
        result.addErrback(creation_failed)

        def exists(ignored):
            if new_volume.locally_owned():
                result = zfs_command(self._reactor,
                                     [b"set", b"readonly=off",
                                      new_filesystem.name])
            else:
                result = zfs_command(self._reactor,
                                     [b"inherit", b"readonly",
                                      new_filesystem.name])
            result.addCallback(lambda _: zfs_command(self._reactor,
                               [b"set", b"mountpoint=" + new_mount_path,
                                new_filesystem.name]))
            return result
        result.addCallback(exists)

    def get(self, volume):
        dataset = volume_to_dataset(volume)
        mount_path = self._mount_root.child(dataset)
        return Filesystem(self._name, dataset, mount_path)

    def enumerate(self):
        listing = _list_filesystems(self._reactor, self._name)

        def listed(filesystems):
            result = set()
            for entry in filesystems:
                dataset, mountpoint = entry
                filesystem = Filesystem(
                    self._name, dataset, FilePath(mountpoint))
                result.add(filesystem)
            return result

        return listing.addCallback(listed)


def _list_filesystems(reactor, pool):
    """Get a listing of all filesystems on a given pool.

    :param pool: A `flocker.volume.filesystems.interface.IStoragePool`
        provider.
    :return: A ``Deferred`` that fires with an iterator, the elements
        of which are ``tuples`` containing the name and mountpoint of each
        filesystem.
    """
    # ZFS list command with a depth of 1, so that only this dataset and its
    # direct children are shown.
    # No headers are printed.
    # name and mountpoint are the properties displayed.
    listing = zfs_command(
        reactor,
        [b"list", b"-d", b"1", b"-H", b"-o", b"name,mountpoint", pool])

    def listed(output, pool):
        for line in output.splitlines():
            name, mountpoint = line.split(b'\t')
            name = name[len(pool) + 1:]
            if name:
                yield (name, mountpoint)

    listing.addCallback(listed, pool)
    return listing

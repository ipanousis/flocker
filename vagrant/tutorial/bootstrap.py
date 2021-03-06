#!/usr/bin/python

# This script builds the base flocker-dev box.

import sys
import os
from subprocess import check_call, check_output
from textwrap import dedent
from urlparse import urljoin

if len(sys.argv) != 4:
    print "Wrong number of arguments."
    raise SystemExit(1)

rpm_version = sys.argv[1]
branch = sys.argv[2]
build_server = sys.argv[3] or 'http://build.clusterhq.com/'

# Make it possible to install flocker-node
rpm_dist = check_output(['rpm', '-E', '%dist']).strip()
zfs_repo_url = (
    'https://s3.amazonaws.com/'
    'archive.zfsonlinux.org/'
    'fedora/zfs-release%s.noarch.rpm') % (rpm_dist,)
check_call(['yum', 'install', '-y',  zfs_repo_url])

clusterhq_repo_url = (
    'https://storage.googleapis.com/'
    'archive.clusterhq.com/'
    'fedora/clusterhq-release%s.noarch.rpm') % (rpm_dist,)
check_call(['yum', 'install', '-y', clusterhq_repo_url])

if branch:
    # If a branch is specified, add a repo pointing at the
    # buildserver repository corresponding to that branch.
    # This repo will be disabled by default.
    with open('/etc/yum.repos.d/clusterhq-build.repo', 'w') as repo:
        result_path = os.path.join('/results/fedora/$releasever/x86_64', branch)
        base_url = urljoin(build_server, result_path)
        repo.write(dedent(b"""
            [clusterhq-build]
            name=clusterhq-build
            baseurl=%s
            gpgcheck=0
            enabled=0
            """) % (base_url,))
    branch_opt = ['--enablerepo=clusterhq-build']
else:
    branch_opt = []

# If a version is specifed, install that version.
# Otherwise install whatever yum decides.
if rpm_version:
    # The buildserver doesn't build dirty versions,
    # so strip that.
    if rpm_version.endswith('.dirty'):
        rpm_version = rpm_version[:-len('.dirty')]
    package = 'flocker-node-%s%s' % (rpm_version, rpm_dist)
else:
    package = 'flocker-node'

# Install flocker-node
check_call(['yum', 'install', '-y'] + branch_opt + [package])

# Enable docker.
# We don't need to start it, since when the box is packaged,
# the machine will be reset.
check_call(['systemctl', 'enable', 'docker'])

# Make it easy to authenticate as root
check_call(['mkdir', '-p', '/root/.ssh'])
check_call(
    ['cp', os.path.expanduser('~vagrant/.ssh/authorized_keys'), '/root/.ssh'])

# Configure GRUB2 to boot kernel with elevator=noop to workaround
# https://github.com/ClusterHQ/flocker/issues/235
with open('/etc/default/grub', 'a') as f:
    f.write('GRUB_CMDLINE_LINUX="${GRUB_CMDLINE_LINUX} elevator=noop"\n')

check_call(['grub2-mkconfig', '-o', '/boot/grub2/grub.cfg'])

# Create a ZFS storage pool backed by a normal filesystem file.  This
# is a bad way to configure ZFS for production use but it is
# convenient for a demo in a VM.
check_call(['mkdir', '-p', '/opt/flocker'])
check_call(['truncate', '--size', '1G', '/opt/flocker/pool-vdev'])
check_call(['zpool', 'create', 'flocker', '/opt/flocker/pool-vdev'])

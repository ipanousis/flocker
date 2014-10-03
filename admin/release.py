# Copyright Hybrid Logic Ltd.  See LICENSE file for details.

"""
Helper utilities for the Flocker release process.

Since this is imported from setup.py, we need to ensure that it only imports
things from the stdlib.
"""

from collections import namedtuple

__all__ = ['rpm_version', 'make_rpm_version']

rpm_version = namedtuple('rpm_version', 'version release')


def make_rpm_version(flocker_version):
    """
    Parse the Flocker version generated by versioneer into an RPM compatible
    version and a release version.
    See: http://fedoraproject.org/wiki/Packaging:NamingGuidelines#Pre-Release_packages

    :param flocker_version: The versioneer style Flocker version string.
    :return: An ``rpm_version`` tuple containing a ``version`` and a
        ``release`` attribute.
    """
    # E.g. 0.1.2-69-gd2ff20c-dirty
    # tag+distance+shortid+dirty
    parts = flocker_version.split('-')
    tag, remainder = parts[0], parts[1:]
    for suffix in ('pre', 'dev'):
        parts = tag.rsplit(suffix, 1)
        if len(parts) == 2:
            # A pre or dev suffix was present. ``version`` is the part before
            # the pre and ``suffix_number`` is the part after the pre, but
            # before the first dash.
            version = parts.pop(0)
            suffix_number = parts[0]
            if suffix_number.isdigit():
                # Given pre or dev number X create a 0 prefixed, `.` separated
                # string of version labels. E.g.
                # 0.1.2pre2  becomes
                # 0.1.2-0.pre.2
                release = ['0', suffix, suffix_number]
            else:
                # Non-integer pre or dev number found.
                raise Exception(
                    'Non-integer value "{}" for "{}". '
                    'Supplied version {}'.format(
                        suffix_number, suffix, flocker_version))
            break
    else:
        # Neither of the expected suffixes was found, the tag can be used as
        # the RPM version
        version = tag
        release = ['1']

    if remainder:
        # The version may also contain a distance, shortid which
        # means that there have been changes since the last
        # tag. Additionally there may be a ``dirty`` suffix which
        # indicates that there are uncommitted changes in the
        # working directory.  We probably don't want to release
        # untagged RPM versions, and this branch should probably
        # trigger and error or a warning. But for now we'll add
        # that extra information to the end of release number.
        # See https://github.com/ClusterHQ/flocker/issues/833
        release.extend(remainder)

    return rpm_version(version, '.'.join(release))


class SumoBuilder(object):
    """
    Motivation:
    * We depend on libraries which are not packaged for the target OS.
    * We depend on newer versions of libraries which have not yet been included in the target OS.

    Disadvantages:
    * We won't be able to take advantage of library security updates shipped by the target OS.
      * But by shipping our own separate dependency packages we will need to be responsible for shipping security patches in those packages.
      * And rather than being responsible only for the security of Flocker, we become responsible for the security of all other packages that depend on that package.
    * Packages will be larger.

    Plan:
    * Create a temporary working dir.
    * Create virtualenv with `--system-site-packages`
      * Allows certain python libraries to be supplied by the operating system.
    * Install flocker from wheel file (which will include all the dependencies).
      * We'll need to keep track of which of our dependencies are provided on each platform and somehow omit those for from the build for that platform. 
    * Generate an RPM version number.
    * Run `fpm` supplying the virtualenv path and version number.


    Followup Issues:
    * Update all pinned dependencies to instead be minimum dependencies.
      * This means that as and when sufficiently new versions of our dependencies are introduced upstream, we can remove them from our sumo build.
      * Those dependencies which are either too old or which are not packaged will be imported from the sumo virtualenv in preference.
      * Eventually we hope that all our dependencies will filter upstream and we will no longer have to bundle them; at which point the `flocker` package itself may be ready to be packaged by upstream distributions.

    Ticket refs:
         * https://github.com/ClusterHQ/flocker/issues/88

    Issue: CI integration (??):
    Update buildbot to build RPMs using new build scripts
    * Issue: create deb, mac, gentoo build slave
    * Issue: install from resulting package from repo and run test suite

    Issue: Client package build (??):
    Sumo packaging of flocker-deploy
    * For deb, RPM, and mac (via homebrew or ...)
    * Proper mac packages. See http://stackoverflow.com/questions/11487596/making-os-x-installer-packages-like-a-pro-xcode4-developer-id-mountain-lion-re

    Client package CI integration

    Misc:
    * separate stable and testing repos for deb and rpm
    * update python-flocker.spec.in requirements (remove most of them)
    * maybe even remove the spec file template and generate_spec function entirely (do we need it?)
    * do we still need to build an SRPM?
    * automatically build a wheel
    * automatically build an sdist
    """
    def build_rpm(self):
        """
        """
        return 'an rpm'
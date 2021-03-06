Release Schedule and Version Numbers
====================================

Goals
-----

The goals of the release schedule are to:

* Make new features and bug fixes available to users as quickly as possible.
* Practice releasing so that we are less likely to make mistakes.
* Improve the automation of releases through experience.

Schedule
--------

We will make a new release of Flocker each week.
This will proceed according to the :doc:`release-process`.
The releases will happen on Tuesday of each week.
If nobody is available in the ClusterHQ organization to create a release, the week will be skipped.

After each release is distributed, the engineer who performed the release will create issues for any improvements which could be made.
The release engineer should then spend 4-8 hours working on making improvements to release process.
If there is an issue that will likely take over 8 hours then they should consult the team manager before starting them.

.. _version-numbers:

Version Numbers
---------------

Released version numbers take the form of ``X.Y.Z``.
The current value of ``X`` is 0 until the project is ready for production.

``Y`` is the "marketing version".
ClusterHQ's marketing department is made aware of the content of a release ahead of time.
If the marketing department decides that this release is sufficiently important to publicize then ``Y`` is incremented and ``Z`` is set to 0.

``Z`` is the "patch version".

Weekly releases will have the version number of the next release with a ``devX`` suffix, where ``X`` starts at ``1`` and is incremented for each weekly release.

Pre-releases will have the version number of the next release with a ``preX`` suffix, where ``X`` starts at ``1`` and is incremented for each pre-release.

For example:

+---------------+-------------------------------------------------+
| ``0.3.0dev1`` | Weekly releases of 0.3.0                        |
+---------------+-------------------------------------------------+
| ``0.3.0dev2`` |                                                 |
+---------------+-------------------------------------------------+
| ``0.3.0pre1`` | Pre-releases of 0.3.0 for acceptance testing    |
+---------------+-------------------------------------------------+
| ``0.3.0pre2`` |                                                 |
+---------------+-------------------------------------------------+
| ``0.3.0``     | 0.3.0 released                                  |
+---------------+-------------------------------------------------+
| ``0.4.0dev1`` | Weekly releases of 0.4.0                        |
+---------------+-------------------------------------------------+
| ``0.3.1pre1`` | Pre-release of an emergency patch release 0.3.1 |
+---------------+-------------------------------------------------+
| ``0.3.1``     | 0.3.1 released                                  |
+---------------+-------------------------------------------------+
| ``0.4.0dev2`` | Weekly releases of 0.4.0 continue               |
+---------------+-------------------------------------------------+

Patch Releases
--------------

ClusterHQ will not be producing patch releases until the project is ready for production.

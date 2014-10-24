# Copyright Hybrid Logic Ltd.  See LICENSE file for details.

"""
Tests for running and managing PostgreSQL with Flocker.
"""
from twisted.trial.unittest import TestCase

from flocker.node._docker import BASE_NAMESPACE, Unit

from .testtools import (assert_expected_deployment, flocker_deploy, get_nodes,
                        require_flocker_cli)


class PostgresTests(TestCase):
    """
    Tests for running and managing PostgreSQL with Flocker.

    Similar to:
    http://doc-dev.clusterhq.com/gettingstarted/examples/postgres.html

    # TODO Link to this file from postgres.rst
    """
    @require_flocker_cli
    def test_postgres(self):
        """
        PostgreSQL and its data can be deployed and moved with FLocker.
        """
        getting_nodes = get_nodes(num_nodes=2)

        getting_nodes.addCallback(deploy)
        return getting_nodes

"""Link ownership compares recorded text without following substituted aliases."""

import unittest

from agent_env_man import link_paths
from agent_env_man.storage import link_matches


class LinkPaths(unittest.TestCase):

    def test_no_alias_resolution_or_normalization(self):
        for actual, expected in [("/other", "/source"), ("/SOURCE", "/source"), ("source", "/source"),
                                 ("/alias/../source", "/source"), ("/source/", "/source")]:
            self.assertFalse(link_paths.same_destination(actual, expected))
        self.assertFalse(link_matches({"kind": "file", "to": "same"}, "same"))
        self.assertFalse(link_paths.same_destination(None, "same"))
        self.assertTrue(link_paths.same_destination("/source", "/source"))

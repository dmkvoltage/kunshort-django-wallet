from __future__ import annotations

import unittest

from django.test.runner import DiscoverRunner


class VerboseTextTestResult(unittest.TextTestResult):
    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self.showAll = True
        self.dots = False

    def getDescription(self, test):
        return str(test)


class VerboseTextTestRunner(unittest.TextTestRunner):
    resultclass = VerboseTextTestResult


class VerboseDiscoverRunner(DiscoverRunner):
    test_runner = VerboseTextTestRunner
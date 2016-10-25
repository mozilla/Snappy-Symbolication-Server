#!/usr/bin/env python
################################################################################
# runTests
#
# Runs all the tests in the test directory
################################################################################
import unittest
import sys
import os
import argparse
import shutil

SYMSERVER_DIR = os.path.dirname(os.path.realpath(__file__))
TEST_DIR = os.path.realpath(os.path.join(SYMSERVER_DIR, "tests"))
if TEST_DIR not in sys.path:
    sys.path.insert(0, TEST_DIR)
from testUtils import TEST_CONFIG_PATH


def main():
    parser = argparse.ArgumentParser(description="Run tests on SymServer")
    parser.add_argument("--config", "-c", metavar="PATH", help="Path to a "
                        "config file. Values in the configuration file will be used as defaults "
                        "when testing. Note that some configutation values will be overridden "
                        "for testing.")
    parser.add_argument("--oldConfig", "-o", action="store_true", help="If "
                        "specified, the same configuration from the last test run will be used "
                        "again. This is overridden by the -c option.")
    parser.add_argument("--noRun", "-n", action="store_true", help="If "
                        "specified, the configuration is set but no tests are run. This is "
                        "helpful if you want to run tests individually. With --oldConfig, this "
                        "does nothing.")
    args = parser.parse_args()
    return runTests(args.config, bool(args.oldConfig), not bool(args.noRun))


def runTests(configPath=None, useOldConfig=False, runTests=True):
    if configPath:
        shutil.copyfile(configPath, TEST_CONFIG_PATH)
    elif not useOldConfig:
        if os.path.exists(TEST_CONFIG_PATH):
            os.remove(TEST_CONFIG_PATH)
    if runTests:
        testLoader = unittest.defaultTestLoader.discover(TEST_DIR)
        testRunner = unittest.TextTestRunner()
        return testRunner.run(testLoader)
    return 0

if __name__ == '__main__':
    sys.exit(main())

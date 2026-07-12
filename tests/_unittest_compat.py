from unittest.mock import patch


class MonkeyPatchCompat:
    def __init__(self, test_case):
        self.test_case = test_case

    def setattr(self, target, name, value):
        patcher = patch.object(target, name, value)
        patcher.start()
        self.test_case.addCleanup(patcher.stop)


def run_with_monkeypatch(test_case, test_function):
    return test_function(MonkeyPatchCompat(test_case))

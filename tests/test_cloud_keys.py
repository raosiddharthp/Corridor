import types

import pytest

from scripts import cloud_keys


class _Recorder:
    def __init__(self, existing=(), fail_on=None):
        self.calls = []
        self.existing = set(existing)
        self.fail_on = fail_on

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command[:3] == ["gcloud", "secrets", "describe"]:
            code = 0 if command[3] in self.existing else 1
        elif self.fail_on and command[:3] == self.fail_on:
            code = 1
        else:
            code = 0
        return types.SimpleNamespace(returncode=code, stdout="", stderr="")


def _writes(recorder, verb):
    return [c for c in recorder.calls if c[0][2] == verb or c[0][3:4] == [verb]]


def test_all_four_secrets_are_created_from_stdin():
    recorder = _Recorder()
    cloud_keys.main([], run=recorder)
    creates = [c for c in recorder.calls if c[0][:3] == ["gcloud", "secrets", "create"]]
    assert {c[0][3] for c in creates} == set(cloud_keys.SECRETS.values())
    for command, kwargs in creates:
        assert "--data-file=-" in command
        assert kwargs["input"]


def test_secrets_are_regional_not_global():
    recorder = _Recorder()
    cloud_keys.main([], run=recorder)
    create = next(c[0] for c in recorder.calls if c[0][:3] == ["gcloud", "secrets", "create"])
    assert "--replication-policy=user-managed" in create
    assert "--locations=europe-west2" in create


def test_no_key_material_appears_in_any_command_line():
    recorder = _Recorder()
    cloud_keys.main([], run=recorder)
    for command, _ in recorder.calls:
        assert "kty" not in " ".join(command)


def test_existing_secrets_are_left_alone_without_rotate():
    recorder = _Recorder(existing=cloud_keys.SECRETS.values())
    assert cloud_keys.main([], run=recorder) == 0
    assert all(c[0][2] == "describe" for c in recorder.calls)


def test_rotate_adds_a_new_version_to_every_secret():
    recorder = _Recorder(existing=cloud_keys.SECRETS.values())
    cloud_keys.main(["--rotate"], run=recorder)
    adds = [c for c in recorder.calls if c[0][:4] == ["gcloud", "secrets", "versions", "add"]]
    assert len(adds) == 4


def test_the_script_never_prints_key_material(capsys):
    cloud_keys.main([], run=_Recorder())
    assert "kty" not in capsys.readouterr().out


def test_a_failed_store_raises_without_leaking_anything():
    recorder = _Recorder(fail_on=["gcloud", "secrets", "create"])
    with pytest.raises(RuntimeError) as error:
        cloud_keys.main([], run=recorder)
    assert "kty" not in str(error.value)

import pipeline.keys as pkeys
from scripts import make_keys


def _parse_env(text):
    env = {}
    for line in text.splitlines():
        if "=" in line:
            name, _, value = line.partition("=")
            env[name] = value.strip("'")
    return env


def test_generated_keys_load_through_the_real_loaders():
    env = make_keys.generate()
    assert pkeys.load_keys(env)
    assert pkeys.load_supplier_signing_key(env)


def test_main_writes_a_usable_env_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert make_keys.main() == 0
    env = _parse_env((tmp_path / ".env").read_text())
    assert pkeys.load_keys(env)
    assert pkeys.load_supplier_signing_key(env)
    assert env["SUPPLIER_URL"].startswith("http://")


def test_main_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    make_keys.main()
    first = (tmp_path / ".env").read_text()
    make_keys.main()
    assert (tmp_path / ".env").read_text() == first


def test_main_never_prints_key_material(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    make_keys.main()
    assert "kty" not in capsys.readouterr().out


def test_main_keeps_existing_env_content(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("INTERPRETER=rule")
    make_keys.main()
    text = (tmp_path / ".env").read_text()
    assert text.startswith("INTERPRETER=rule\n")
    assert pkeys.USER_ENV in text

from pathlib import Path

ROOT = Path(__file__).parent.parent


def _lines(name):
    return [line.strip() for line in (ROOT / name).read_text().splitlines() if line.strip()]


def test_git_is_only_in_the_build_stage():
    stages = (ROOT / "Dockerfile").read_text().split("FROM ")
    assert len(stages) == 3
    assert "git" in stages[1]
    assert "apt-get" not in stages[2]


def test_the_image_runs_as_a_non_root_user():
    assert "USER corridor" in (ROOT / "Dockerfile").read_text()


def test_the_image_carries_all_three_code_packages():
    text = (ROOT / "Dockerfile").read_text()
    for package in ("app", "pipeline", "supplier"):
        assert f"COPY {package} ./{package}" in text


def test_secrets_never_enter_the_build_context():
    for name in (".dockerignore", ".gcloudignore"):
        lines = _lines(name)
        for pattern in (".env", "*.pem", "*.key"):
            assert pattern in lines, (name, pattern)


def test_the_code_is_not_ignored():
    for name in (".dockerignore", ".gcloudignore"):
        lines = _lines(name)
        for code in ("app", "pipeline", "supplier", "/app", "/pipeline", "/supplier"):
            assert code not in lines, (name, code)


def test_the_design_page_is_only_ignored_at_the_root_for_gcloud():
    lines = _lines(".gcloudignore")
    assert "/index.html" in lines
    assert "index.html" not in lines


def test_runtime_requirements_are_pinned_and_complete():
    lines = _lines("requirements.txt")
    assert any(line.startswith("ap2 @ git+") for line in lines)
    for name in ("fastapi", "uvicorn", "httpx", "jwcrypto"):
        assert any(line.startswith(f"{name}==") for line in lines), name

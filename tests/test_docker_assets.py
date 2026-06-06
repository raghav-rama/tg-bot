from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_uses_runtime_entrypoint_for_volume_permissions() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()

    assert "COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh" in dockerfile
    assert "ENTRYPOINT [\"docker-entrypoint.sh\"]" in dockerfile
    assert 'CMD ["uvicorn", "app.main:app"' in dockerfile
    assert "\nUSER app\n" not in dockerfile


def test_entrypoint_prepares_sqlite_parent_before_dropping_privileges() -> None:
    entrypoint = (REPO_ROOT / "docker-entrypoint.sh").read_text()

    assert "SQLITE_PATH" in entrypoint
    assert "sqlite_parent=" in entrypoint
    assert "mkdir -p \"$sqlite_parent\"" in entrypoint
    assert "chown -R \"$APP_USER:$APP_GROUP\" \"$sqlite_parent\"" in entrypoint
    assert 'exec su -s /bin/sh "$APP_USER"' in entrypoint

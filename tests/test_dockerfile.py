import json

import pytest

from wheelgap.cli import main
from wheelgap.dockerfile import DockerfileError, ImageTarget, last_from, parse_from, read_dockerfile


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("python:3.13-alpine", ImageTarget("3.13", "musl-x86_64", musl="1.2")),
        ("--platform=linux/arm64 python:3.12-slim", ImageTarget("3.12", "linux-aarch64")),
        ("python:3.14-slim-trixie", ImageTarget("3.14", "linux-x86_64", glibc="2.41")),
        ("python:3.13-bookworm", ImageTarget("3.13", "linux-x86_64", glibc="2.36")),
        ("python:3.11-slim-bullseye", ImageTarget("3.11", "linux-x86_64", glibc="2.31")),
        ("python:3.13.1-alpine3.22 AS runtime", ImageTarget("3.13", "musl-x86_64", musl="1.2")),
        ("--platform linux/arm64 python:3.13-alpine", ImageTarget("3.13", "musl-aarch64", musl="1.2")),
        ("docker.io/library/python:3.12", ImageTarget("3.12", "linux-x86_64")),
        ("python:3.13-slim@sha256:" + "0" * 64, ImageTarget("3.13", "linux-x86_64")),
        ("python:3.15.0a1-slim", ImageTarget("3.15", "linux-x86_64")),
        ("python:3.13-windowsservercore-ltsc2022", ImageTarget("3.13", "win-amd64")),
    ],
)
def test_parse_from(line, expected):
    assert parse_from(line) == expected


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("ubuntu:24.04", "only the official python images"),
        ("python", "must start with a Python version"),
        ("python:latest", "must start with a Python version"),
        ("python:${PY}-slim", "build arguments"),
        ("--platform=$BUILDPLATFORM python:3.13", "build arguments"),
        ("--platform=linux/s390x python:3.13", "only linux/amd64"),
        ("python:3.13-slim-buster", "unknown image variant 'buster'"),
    ],
)
def test_parse_from_errors(line, message):
    with pytest.raises(DockerfileError, match=message):
        parse_from(line)


def test_last_from_takes_the_final_stage():
    text = (
        "# syntax=docker/dockerfile:1\n"
        "FROM python:3.12-bookworm AS build\n"
        "RUN pip wheel . \\\n"
        "    -w /wheels\n"
        "from --platform=linux/arm64 \\\n"
        "    python:3.13-alpine\n"
        "COPY --from=build /wheels /wheels\n"
    )
    assert last_from(text) == "--platform=linux/arm64      python:3.13-alpine"
    assert parse_from(last_from(text)) == ImageTarget("3.13", "musl-aarch64", musl="1.2")


def test_no_from(tmp_path):
    path = tmp_path / "Dockerfile"
    path.write_text("RUN echo hi\n")
    with pytest.raises(DockerfileError, match="no FROM line"):
        read_dockerfile(path)


def test_cli_dockerfile(capsys, fixtures, tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.13-alpine\n")
    code = main([str(fixtures / "uvproj"), "--dockerfile", str(dockerfile), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert code in (0, 1)
    assert [(t["python"], t["platform"]) for t in data["targets"]] == [("3.13", "musl-x86_64")]


def test_cli_flags_beat_dockerfile(capsys, fixtures, tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.13-alpine\n")
    main([str(fixtures / "uvproj"), "--dockerfile", str(dockerfile), "-t", "win-amd64", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert [(t["python"], t["platform"]) for t in data["targets"]] == [("3.13", "win-amd64")]


def test_cli_bad_dockerfile_exit_2(capsys, fixtures, tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM node:22\n")
    assert main([str(fixtures / "uvproj"), "--dockerfile", str(dockerfile)]) == 2
    assert "only the official python images" in capsys.readouterr().err

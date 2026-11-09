"""Turn the last FROM line of a Dockerfile into a wheelgap target (official `python` images only)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Debian release in the image tag -> its glibc version.
DEBIAN_GLIBC = {"bullseye": "2.31", "bookworm": "2.36", "trixie": "2.41"}
ALPINE_MUSL = "1.2"
# docker --platform -> wheelgap arch
ARCHES = {
    "linux/amd64": "x86_64",
    "linux/x86_64": "x86_64",
    "linux/arm64": "aarch64",
    "linux/arm64/v8": "aarch64",
    "linux/aarch64": "aarch64",
}
WINDOWS_VARIANTS = ("windowsservercore", "nanoserver")
IMAGE_NAMES = ("python", "library/python", "docker.io/library/python", "docker.io/python")

_TAG_RE = re.compile(r"^(\d+)\.(\d+)(?:\.\d+)?(?:(?:a|b|rc)\d+)?(?:-(.+))?$")


class DockerfileError(ValueError):
    pass


@dataclass(frozen=True)
class ImageTarget:
    python: str
    platform: str
    glibc: str | None = None
    musl: str | None = None


def last_from(text: str) -> str:
    """The arguments of the last FROM instruction, with line continuations joined."""
    joined = re.sub(r"\\\r?\n", " ", text)
    found = None
    for line in joined.splitlines():
        words = line.strip().split(None, 1)
        if len(words) == 2 and words[0].upper() == "FROM":
            found = words[1]
    if found is None:
        raise DockerfileError("no FROM line found")
    return found


def parse_from(args: str) -> ImageTarget:
    """Parse `[--platform=P] image[:tag][@digest] [AS name]`."""
    words = args.split()
    platform = None
    while words and words[0].startswith("--"):
        flag = words.pop(0)
        if flag.startswith("--platform="):
            platform = flag.split("=", 1)[1]
        elif flag == "--platform" and words:
            platform = words.pop(0)
    if not words:
        raise DockerfileError(f"FROM {args}: no image")
    return parse_image(words[0], platform)


def parse_image(image: str, platform: str | None = None) -> ImageTarget:
    if "$" in image or (platform and "$" in platform):
        raise DockerfileError(f"{image}: build arguments are not supported, pass -p/-t instead")
    image = image.split("@", 1)[0]
    name, _, tag = image.rpartition(":") if ":" in image.rsplit("/", 1)[-1] else (image, "", "")
    if name.lower() not in IMAGE_NAMES:
        raise DockerfileError(f"{image}: only the official python images are supported, pass -p/-t instead")
    m = _TAG_RE.match(tag)
    if not m:
        raise DockerfileError(f"{image}: the tag must start with a Python version like 3.13")
    python = f"{m.group(1)}.{m.group(2)}"
    variant = (m.group(3) or "").lower().split("-") if m.group(3) else []

    if any(part.startswith("alpine") for part in variant):
        family, glibc, musl = "musl", None, ALPINE_MUSL
    elif any(part in WINDOWS_VARIANTS for part in variant):
        if platform:
            raise DockerfileError(f"{image}: --platform is not supported for Windows images")
        return ImageTarget(python, "win-amd64")
    else:
        family, musl = "linux", None
        unknown = [part for part in variant if part not in DEBIAN_GLIBC and part != "slim"]
        if unknown:
            raise DockerfileError(f"{image}: unknown image variant '{'-'.join(unknown)}'")
        glibc = next((DEBIAN_GLIBC[part] for part in variant if part in DEBIAN_GLIBC), None)

    arch = "x86_64"
    if platform:
        if platform.lower() not in ARCHES:
            raise DockerfileError(f"--platform={platform}: only {', '.join(ARCHES)} are supported")
        arch = ARCHES[platform.lower()]
    return ImageTarget(python, f"{family}-{arch}", glibc, musl)


def read_dockerfile(path: Path) -> ImageTarget:
    try:
        return parse_from(last_from(path.read_text(encoding="utf-8")))
    except DockerfileError as e:
        raise DockerfileError(f"{path}: {e}") from None

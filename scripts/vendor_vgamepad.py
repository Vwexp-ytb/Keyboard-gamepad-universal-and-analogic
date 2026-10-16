from __future__ import annotations

import hashlib
import importlib.metadata
import shutil
import sys
import sysconfig
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from urllib.request import urlopen


URL = "https://files.pythonhosted.org/packages/8a/54/0eaddc33f84247963af078f364b37153d09fcd6cdc398f243ec3e8842c56/vgamepad-0.1.0.tar.gz"
SHA256 = "57f6bd01aec0c172947517fb782d150ef9b285f7f4d524c317374fa5c24a89de"
ARCHIVE_PREFIX = "vgamepad-0.1.0/vgamepad/"


def prepare_vgamepad() -> Path:
    site_packages = Path(sysconfig.get_paths()["purelib"])
    destination = site_packages / "vgamepad"
    if destination.exists():
        try:
            installed_version = importlib.metadata.version("vgamepad")
        except importlib.metadata.PackageNotFoundError:
            installed_version = "unknown"
        if installed_version == "0.1.0":
            return destination
        raise RuntimeError(f"Refus de remplacer le paquet vgamepad existant ({installed_version}).")

    with tempfile.TemporaryDirectory(prefix="ace60-vgamepad-") as temp_name:
        archive_path = Path(temp_name) / "vgamepad.tar.gz"
        digest = hashlib.sha256()
        with urlopen(URL, timeout=60) as response, archive_path.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != SHA256:
            raise RuntimeError("La somme de contrôle de l'archive vgamepad ne correspond pas.")

        staging = Path(temp_name) / "vgamepad"
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.name.startswith(ARCHIVE_PREFIX) or not member.isfile():
                    continue
                relative = PurePosixPath(member.name[len(ARCHIVE_PREFIX):])
                if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
                    continue
                target = staging.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    continue
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        if not (staging / "__init__.py").is_file():
            raise RuntimeError("L'archive vgamepad ne contient pas son module Python attendu.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staging, destination)
    print(f"vgamepad préparé dans l'environnement de build : {destination}")
    return destination


if __name__ == "__main__":
    prepare_vgamepad()

import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

import yaml


MANIFEST = pathlib.Path("fetch_deps.yaml")
LOCKFILE = pathlib.Path("fetch_deps.lock")
GITIGNORE = pathlib.Path(".gitignore")
CACHE_DIR = pathlib.Path(".cache") / "fetch_deps"

GITIGNORE_BEGIN = "# BEGIN fetch_deps"
GITIGNORE_END = "# END fetch_deps"


class DependencyError(Exception):
    """An expected dependency-management error."""


def log(message=""):
    print(message, flush=True)


def run_git(*args, cwd=None, quiet=False):
    """Run Git and provide useful diagnostics on failure."""
    command = ["git", *args]

    if not quiet:
        log(f"    $ {' '.join(command)}")

    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DependencyError(
            "Git was not found on PATH. "
            "Please install Git and try again."
        ) from exc
    except OSError as exc:
        raise DependencyError(
            f"Could not execute Git: {exc}"
        ) from exc

    if result.returncode != 0:
        details = []

        if result.stderr.strip():
            details.append(result.stderr.strip())

        if result.stdout.strip():
            details.append(
                f"stdout:\n{result.stdout.strip()}"
            )

        raise DependencyError(
            f"Git command failed with exit code "
            f"{result.returncode}:\n"
            f"  command: {' '.join(command)}\n"
            f"{chr(10).join(details) or '  (no diagnostic output)'}"
        )

    return result.stdout.strip()


def cache_path(source):
    """Return a stable cache directory for a repository URL."""
    digest = hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()[:16]

    return CACHE_DIR / digest


def load_manifest():
    if not MANIFEST.exists():
        raise DependencyError(
            f"Manifest not found:\n"
            f"  {MANIFEST.resolve()}"
        )

    try:
        text = MANIFEST.read_text(
            encoding="utf-8"
        )
    except OSError as exc:
        raise DependencyError(
            f"Could not read {MANIFEST}: {exc}"
        ) from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise DependencyError(
            f"Invalid YAML in {MANIFEST}:\n{exc}"
        ) from exc

    if data is None:
        return {}

    if not isinstance(data, dict):
        raise DependencyError(
            f"{MANIFEST} must contain a YAML mapping."
        )

    return data


def load_lock():
    if not LOCKFILE.exists():
        return {
            "version": 2,
            "files": {},
        }

    try:
        text = LOCKFILE.read_text(
            encoding="utf-8"
        )
    except OSError as exc:
        raise DependencyError(
            f"Could not read {LOCKFILE}: {exc}"
        ) from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DependencyError(
            f"Invalid JSON in {LOCKFILE}:\n{exc}"
        ) from exc

    if not isinstance(data, dict):
        raise DependencyError(
            f"{LOCKFILE} must contain a JSON object."
        )

    version = data.get("version")

    if version not in {1, 2}:
        raise DependencyError(
            f"Unsupported {LOCKFILE} version: {version!r}"
        )

    files = data.get("files")

    if not isinstance(files, dict):
        raise DependencyError(
            f"{LOCKFILE} has an invalid 'files' section."
        )

    # Version 1 locks did not support directories. They remain
    # readable so existing single-file projects don't break.
    return data


def save_lock(files):
    data = {
        "version": 2,
        "files": dict(sorted(files.items())),
    }

    temporary = LOCKFILE.with_name(
        LOCKFILE.name + ".tmp"
    )

    try:
        temporary.write_text(
            json.dumps(
                data,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )

        temporary.replace(LOCKFILE)

    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass

        raise DependencyError(
            f"Could not write {LOCKFILE}: {exc}"
        ) from exc


def validate_destination(dest):
    """Validate and normalize a project-relative destination."""
    if not isinstance(dest, str) or not dest.strip():
        raise DependencyError(
            f"Invalid destination: {dest!r}"
        )

    path = pathlib.Path(dest)

    if path.is_absolute():
        raise DependencyError(
            f"Destination must be relative to the project root: "
            f"{dest}"
        )

    project_root = pathlib.Path.cwd().resolve()
    resolved = path.resolve()

    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise DependencyError(
            f"Destination escapes the project directory: "
            f"{dest}"
        ) from exc

    return path.as_posix()


def destination_path(dest):
    return pathlib.Path(dest)


def path_is_same_or_child(path, parent):
    """
    Return True if path is the same as parent or is underneath parent.
    """
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def validate_manifest(data):
    """
    Validate the manifest completely before making filesystem changes.

    Returns a normalized dependency map.

    Each entry has:
      type
      source
      revision/path/etc.
      kind = file or directory
    """
    desired = {}

    for source, spec in data.items():
        if not isinstance(source, str) or not source:
            raise DependencyError(
                f"Invalid dependency source: {source!r}"
            )

        if not isinstance(spec, dict):
            raise DependencyError(
                f"Dependency '{source}' must be a mapping."
            )

        dependency_type = spec.get("type")

        if dependency_type not in {"git", "url"}:
            raise DependencyError(
                f"Dependency '{source}' must specify "
                f"'type: git' or 'type: url'."
            )

        if dependency_type == "git":
            revision = spec.get("revision")

            if not isinstance(revision, str) or not revision:
                raise DependencyError(
                    f"Git dependency '{source}' is missing "
                    f"a valid 'revision'."
                )

            files = spec.get("files")

            if not isinstance(files, list):
                raise DependencyError(
                    f"Git dependency '{source}' must contain "
                    f"a 'files' list."
                )

            for index, entry in enumerate(files):
                if not isinstance(entry, dict):
                    raise DependencyError(
                        f"{source}: files[{index}] must be a mapping."
                    )

                if "path" not in entry:
                    raise DependencyError(
                        f"{source}: files[{index}] is missing 'path'."
                    )

                if "dest" not in entry:
                    raise DependencyError(
                        f"{source}: files[{index}] is missing 'dest'."
                    )

                repo_path = str(
                    entry["path"]
                ).lstrip("/")

                dest = validate_destination(
                    str(entry["dest"])
                )

                if dest in desired:
                    raise DependencyError(
                        f"Multiple dependencies specify destination:\n"
                        f"  {dest}\n\n"
                        f"Existing dependency: "
                        f"{desired[dest]['source']}\n"
                        f"New dependency: {source}"
                    )

                desired[dest] = {
                    "type": "git",
                    "source": source,
                    "revision": revision,
                    "path": repo_path,
                    "kind": "unknown",
                }

        else:
            if "dest" not in spec:
                raise DependencyError(
                    f"URL dependency '{source}' is missing "
                    f"'dest'."
                )

            dest = validate_destination(
                str(spec["dest"])
            )

            if dest in desired:
                raise DependencyError(
                    f"Multiple dependencies specify destination:\n"
                    f"  {dest}\n\n"
                    f"Existing dependency: "
                    f"{desired[dest]['source']}\n"
                    f"New dependency: {source}"
                )

            desired[dest] = {
                "type": "url",
                "source": source,
                "kind": "file",
            }

    # Check for destination collisions between files and directories.
    destinations = list(desired.keys())

    for i, first in enumerate(destinations):
        first_path = destination_path(first)

        for second in destinations[i + 1:]:
            second_path = destination_path(second)

            if (
                path_is_same_or_child(
                    first_path,
                    second_path,
                )
                or path_is_same_or_child(
                    second_path,
                    first_path,
                )
            ):
                raise DependencyError(
                    "Dependency destinations overlap:\n"
                    f"  {first}\n"
                    f"  {second}\n\n"
                    "A dependency destination cannot contain "
                    "another dependency destination."
                )

    return desired


def lock_entry_matches(
    destination,
    desired_entry,
    old_lock_files,
):
    """
    Check whether a dependency can be skipped without Git/network access.

    The destination contents are intentionally not hashed or inspected.
    """
    old_entry = old_lock_files.get(destination)

    if old_entry is None:
        return False

    if desired_entry["kind"] == "unknown":
        # We don't know whether the repository path is a file or
        # directory until we inspect the repository.
        return False

    if old_entry.get("type") != desired_entry["type"]:
        return False

    if old_entry.get("source") != desired_entry["source"]:
        return False

    if desired_entry["type"] == "url":
        return (
            destination_path(destination).is_file()
        )

    if old_entry.get("revision") != desired_entry["revision"]:
        return False

    if old_entry.get("path") != desired_entry["path"]:
        return False

    if old_entry.get("kind") != desired_entry["kind"]:
        return False

    destination_path_obj = destination_path(destination)

    if desired_entry["kind"] == "file":
        return destination_path_obj.is_file()

    if desired_entry["kind"] != "directory":
        return False

    if not destination_path_obj.is_dir():
        return False

    managed_files = old_entry.get("files")

    if not isinstance(managed_files, list):
        return False

    # If any previously managed file has disappeared, we need to
    # fetch the repository so it can be restored.
    for relative_path in managed_files:
        local_path = (
            destination_path_obj
            / relative_path
        )

        if not local_path.is_file():
            return False

    return True


def prepare_repo(source, revision):
    """
    Make sure the requested revision exists in the cache.

    This function is only called when a dependency actually needs
    to be fetched.
    """
    CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    repo = cache_path(source)

    log(f"  Cache: {repo}")

    if not repo.exists():
        log("  Repository is not cached; cloning...")

        run_git(
            "clone",
            "--no-checkout",
            source,
            str(repo),
        )

    elif not (repo / ".git").exists():
        raise DependencyError(
            f"Cache directory exists but is not a Git repository:\n"
            f"  {repo}\n\n"
            f"Delete that directory and run the script again."
        )

    else:
        log("  Repository is cached.")
        log("  Fetching repository data...")

        run_git(
            "fetch",
            "--quiet",
            "origin",
            cwd=repo,
        )

    log(f"  Verifying revision: {revision}")

    try:
        run_git(
            "cat-file",
            "-e",
            f"{revision}^{{commit}}",
            cwd=repo,
            quiet=True,
        )
    except DependencyError as exc:
        raise DependencyError(
            f"Revision '{revision}' was not found in:\n"
            f"  {source}\n\n"
            f"Git reported:\n{exc}"
        ) from exc

    log(f"  Checking out {revision}...")

    run_git(
        "checkout",
        "--quiet",
        "--force",
        revision,
        cwd=repo,
    )

    return repo


def check_destination_safety(
    destination,
    previous_entry,
):
    """
    Never overwrite an unmanaged existing file.

    A managed file may be replaced when its dependency changes.
    """
    if not destination.exists():
        return

    if destination.is_dir():
        raise DependencyError(
            f"Destination is an existing directory:\n"
            f"  {destination}"
        )

    if previous_entry is None:
        raise DependencyError(
            f"Refusing to overwrite unmanaged file:\n"
            f"  {destination}\n\n"
            f"The file exists but is not recorded in "
            f"{LOCKFILE.name}."
        )


def check_directory_destination_safety(
    destination,
    previous_entry,
):
    """
    Validate a directory dependency destination.

    An existing directory is fine. An existing file is not.
    """
    if not destination.exists():
        return

    if destination.is_file():
        if previous_entry is None:
            raise DependencyError(
                f"Refusing to overwrite unmanaged file:\n"
                f"  {destination}"
            )

        raise DependencyError(
            f"Dependency now requires a directory, but the "
            f"destination is a file:\n"
            f"  {destination}"
        )


def copy_file(
    source_path,
    destination,
    previous_entry,
):
    check_destination_safety(
        destination,
        previous_entry,
    )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = destination.with_name(
        destination.name + ".tmp"
    )

    try:
        shutil.copy2(
            source_path,
            temporary,
        )

        temporary.replace(destination)

    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass

        raise DependencyError(
            f"Could not copy:\n"
            f"  {source_path}\n"
            f"to:\n"
            f"  {destination}\n"
            f"Reason: {exc}"
        ) from exc


def list_directory_files(directory):
    """
    Return all files under a repository directory as paths relative
    to that directory.

    Symlinks are rejected rather than following them.
    """
    result = []

    for path in directory.rglob("*"):
        if path.is_symlink():
            raise DependencyError(
                f"Symlinks are not supported in directory dependencies:\n"
                f"  {path}"
            )

        if path.is_file():
            result.append(
                path.relative_to(directory).as_posix()
            )

    return sorted(result)


def copy_directory(
    source_directory,
    destination,
    previous_entry,
):
    """
    Copy the contents of source_directory into destination.

    Files previously managed by this dependency but absent from the
    new revision are removed. Other local files are left alone.
    """
    check_directory_destination_safety(
        destination,
        previous_entry,
    )

    destination.mkdir(
        parents=True,
        exist_ok=True,
    )

    current_files = list_directory_files(
        source_directory
    )

    current_set = set(current_files)

    previous_files = set()

    if previous_entry:
        previous_files_value = previous_entry.get(
            "files",
            [],
        )

        if isinstance(previous_files_value, list):
            previous_files = set(
                previous_files_value
            )

    # Remove files that were previously managed by this exact
    # directory dependency but no longer exist upstream.
    for relative_path in sorted(
        previous_files - current_set
    ):
        local_path = (
            destination / relative_path
        )

        if not local_path.exists():
            continue

        if local_path.is_dir():
            raise DependencyError(
                f"Previously managed path became a directory:\n"
                f"  {local_path}\n\n"
                f"Refusing to remove it automatically."
            )

        try:
            local_path.unlink()
        except OSError as exc:
            raise DependencyError(
                f"Could not remove stale dependency file:\n"
                f"  {local_path}\n"
                f"Reason: {exc}"
            ) from exc

        log(f"    − {relative_path}")

    # Copy current files.
    for relative_path in current_files:
        source_path = (
            source_directory
            / relative_path
        )

        destination_path_obj = (
            destination
            / relative_path
        )

        # If this destination already exists and was not managed
        # by the previous lock entry, refuse to overwrite it.
        previous_file_entry = (
            previous_entry
            if relative_path in previous_files
            else None
        )

        copy_file(
            source_path,
            destination_path_obj,
            previous_file_entry,
        )

        log(f"    ✓ {relative_path}")

    return current_files


def download_file(
    source,
    destination,
    previous_entry,
):
    check_destination_safety(
        destination,
        previous_entry,
    )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = destination.with_name(
        destination.name + ".tmp"
    )

    try:
        log(f"  Downloading {source}")

        with urllib.request.urlopen(source) as response:
            with temporary.open("wb") as output:
                shutil.copyfileobj(
                    response,
                    output,
                )

        temporary.replace(destination)

    except urllib.error.HTTPError as exc:
        temporary.unlink(missing_ok=True)

        raise DependencyError(
            f"HTTP error downloading {source}: "
            f"{exc.code} {exc.reason}"
        ) from exc

    except urllib.error.URLError as exc:
        temporary.unlink(missing_ok=True)

        raise DependencyError(
            f"URL error downloading {source}: "
            f"{exc.reason}"
        ) from exc

    except OSError as exc:
        temporary.unlink(missing_ok=True)

        raise DependencyError(
            f"Could not write downloaded file "
            f"to {destination}: {exc}"
        ) from exc


def remove_stale_files(
    old_lock_files,
    new_lock_files,
):
    """
    Remove files/directories previously managed but no longer
    present in the manifest.

    Directory dependencies only remove the individual files that
    they previously managed. The directory itself is not removed
    if it contains user-created files.
    """
    stale = (
        set(old_lock_files)
        - set(new_lock_files)
    )

    if not stale:
        return 0

    removed = 0
    project_root = pathlib.Path.cwd().resolve()

    log("Removing stale dependency files:")

    for dest in sorted(stale):
        entry = old_lock_files[dest]
        destination = destination_path(dest)

        if entry.get("kind") == "directory":
            managed_files = entry.get(
                "files",
                [],
            )

            if not isinstance(managed_files, list):
                raise DependencyError(
                    f"Invalid directory entry in {LOCKFILE}:\n"
                    f"  {dest}"
                )

            for relative_path in managed_files:
                path = (
                    destination
                    / relative_path
                )

                if not path.exists():
                    continue

                if path.is_dir():
                    raise DependencyError(
                        f"Previously managed path is now a directory:\n"
                        f"  {path}\n\n"
                        f"Refusing to remove it automatically."
                    )

                try:
                    path.unlink()
                except OSError as exc:
                    raise DependencyError(
                        f"Could not remove stale dependency file:\n"
                        f"  {path}\n"
                        f"Reason: {exc}"
                    ) from exc

                log(
                    f"  − {path.as_posix()}"
                )
                removed += 1

            # Remove empty directories, but never remove directories
            # containing user-created files.
            if destination.exists():
                parent = destination

                while (
                    parent.resolve() != project_root
                    and parent.exists()
                ):
                    try:
                        parent.rmdir()
                    except OSError:
                        break

                    parent = parent.parent

            continue

        # Normal single-file dependency.
        if not destination.exists():
            continue

        if destination.is_dir():
            raise DependencyError(
                f"Previously managed file is now a directory:\n"
                f"  {destination}\n\n"
                f"Refusing to remove it automatically."
            )

        try:
            destination.unlink()
        except OSError as exc:
            raise DependencyError(
                f"Could not remove stale dependency file:\n"
                f"  {destination}\n"
                f"Reason: {exc}"
            ) from exc

        log(f"  − {dest}")
        removed += 1

        parent = destination.parent

        while (
            parent.resolve() != project_root
            and parent.exists()
        ):
            try:
                parent.rmdir()
            except OSError:
                break

            parent = parent.parent

    return removed


def update_gitignore(lock_files):
    """
    Replace only the fetch_deps-owned section of .gitignore.
    """
    entries = [CACHE_DIR.as_posix()]

    for dest, entry in sorted(
        lock_files.items()
    ):
        entries.append(dest)

    generated = "\n".join(
        [
            GITIGNORE_BEGIN,
            *entries,
            GITIGNORE_END,
        ]
    )

    try:
        existing = (
            GITIGNORE.read_text(
                encoding="utf-8"
            )
            if GITIGNORE.exists()
            else ""
        )
    except OSError as exc:
        raise DependencyError(
            f"Could not read {GITIGNORE}: {exc}"
        ) from exc

    begin = existing.find(GITIGNORE_BEGIN)
    end = existing.find(GITIGNORE_END)

    if begin != -1 and end == -1:
        raise DependencyError(
            f"{GITIGNORE} contains '{GITIGNORE_BEGIN}' "
            f"but no matching '{GITIGNORE_END}'."
        )

    if begin != -1:
        end += len(GITIGNORE_END)

        new_contents = (
            existing[:begin]
            + generated
            + existing[end:]
        )
    else:
        separator = (
            ""
            if not existing
            or existing.endswith("\n")
            else "\n"
        )

        new_contents = (
            existing
            + separator
            + "\n"
            + generated
            + "\n"
        )

    if new_contents == existing:
        return

    try:
        GITIGNORE.write_text(
            new_contents,
            encoding="utf-8",
        )
    except OSError as exc:
        raise DependencyError(
            f"Could not write {GITIGNORE}: {exc}"
        ) from exc


def sync():
    log("=== fetch_deps ===")

    data = load_manifest()
    old_lock = load_lock()

    old_lock_files = old_lock["files"]
    desired = validate_manifest(data)

    new_lock_files = {}

    skipped = 0
    fetched = 0

    # -------------------------------------------------------------
    # Fast path.
    #
    # We can skip a dependency entirely if the lockfile tells us
    # exactly what it is and all expected local files exist.
    #
    # Crucially, this happens BEFORE touching Git.
    # -------------------------------------------------------------
    for dest in sorted(desired):
        entry = desired[dest]
        destination = destination_path(dest)

        if entry["type"] == "url":
            entry["kind"] = "file"

        if entry["kind"] != "unknown":
            if lock_entry_matches(
                dest,
                entry,
                old_lock_files,
            ):
                new_lock_files[dest] = {
                    key: value
                    for key, value in entry.items()
                    if key != "kind"
                }

                # For directory entries we need to retain the
                # list of managed files from the old lock.
                if (
                    entry["kind"] == "directory"
                    and old_lock_files[dest].get("files")
                ):
                    new_lock_files[dest]["kind"] = "directory"
                    new_lock_files[dest]["files"] = (
                        old_lock_files[dest]["files"]
                    )

                skipped += 1

    # -------------------------------------------------------------
    # Anything not satisfied by the fast path requires Git/network
    # access.
    # -------------------------------------------------------------
    for dest in sorted(desired):
        entry = desired[dest]

        if dest in new_lock_files:
            continue

        destination = destination_path(dest)
        previous_entry = old_lock_files.get(dest)

        log()
        log("=" * 70)

        if entry["type"] == "git":
            source = entry["source"]
            revision = entry["revision"]
            repo_path = pathlib.Path(entry["path"])

            log("Git dependency:")
            log(f"  source:   {source}")
            log(f"  revision: {revision}")
            log(f"  path:     {entry['path']}")
            log(f"  dest:     {dest}")

            repo = prepare_repo(
                source,
                revision,
            )

            source_path = repo / repo_path

            if not source_path.exists():
                raise DependencyError(
                    f"Path does not exist in repository:\n"
                    f"  {entry['path']}\n"
                    f"repository: {source}\n"
                    f"revision: {revision}"
                )

            if source_path.is_symlink():
                raise DependencyError(
                    f"Symlinks are not supported as dependency paths:\n"
                    f"  {entry['path']}"
                )

            if source_path.is_file():
                entry["kind"] = "file"

                copy_file(
                    source_path,
                    destination,
                    previous_entry,
                )

                new_lock_files[dest] = {
                    "type": "git",
                    "kind": "file",
                    "source": source,
                    "revision": revision,
                    "path": entry["path"],
                }

                log("  ✓ copied")
                fetched += 1

            elif source_path.is_dir():
                entry["kind"] = "directory"

                current_files = copy_directory(
                    source_path,
                    destination,
                    previous_entry,
                )

                new_lock_files[dest] = {
                    "type": "git",
                    "kind": "directory",
                    "source": source,
                    "revision": revision,
                    "path": entry["path"],
                    "files": current_files,
                }

                log(
                    f"  ✓ copied {len(current_files)} file(s)"
                )
                fetched += 1

            else:
                raise DependencyError(
                    f"Unsupported repository path:\n"
                    f"  {entry['path']}"
                )

        elif entry["type"] == "url":
            source = entry["source"]

            log("URL dependency:")
            log(f"  source: {source}")
            log(f"  dest:   {dest}")

            download_file(
                source,
                destination,
                previous_entry,
            )

            new_lock_files[dest] = {
                "type": "url",
                "kind": "file",
                "source": source,
            }

            log("  ✓ downloaded")
            fetched += 1

    log()

    removed = remove_stale_files(
        old_lock_files,
        new_lock_files,
    )

    save_lock(new_lock_files)
    update_gitignore(new_lock_files)

    if fetched == 0 and removed == 0:
        log(
            f"fetch_deps: up to date "
            f"({skipped} dependency(s))"
        )
    else:
        log(
            f"fetch_deps: synchronized "
            f"({fetched} fetched, "
            f"{removed} removed, "
            f"{skipped} unchanged)"
        )


def main():
    try:
        sync()

    except DependencyError as exc:
        log()
        log("!" * 70)
        log("ERROR")
        log("!" * 70)
        log(str(exc))
        log("!" * 70)
        sys.exit(1)

    except KeyboardInterrupt:
        log()
        log("Interrupted.")
        sys.exit(130)

    except Exception as exc:
        log()
        log("!" * 70)
        log("UNEXPECTED ERROR")
        log("!" * 70)
        log(f"{type(exc).__name__}: {exc}")
        log("!" * 70)
        sys.exit(1)


if __name__ == "__main__":
    main()

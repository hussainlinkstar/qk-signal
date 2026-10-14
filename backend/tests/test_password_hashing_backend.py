"""Regression guard for password-hash compatibility.

Every password path in the app goes through ``core.password_hashing``, which
calls the ``bcrypt`` package directly. This file pins the properties that
silently break logins: the stored format (``$2b$`` cost 12), verification of
hashes written by every previous hashing era, and the 72-byte truncation that
passlib applied and that must be preserved byte-for-byte.

The vectors below are committed test data, not credentials. Each is a bcrypt
digest of a plaintext stated in this file, generated ad hoc, and corresponds
to no account anywhere.

SIGV2-1212: one of those vectors is only safe on the pinned bcrypt. A ``$2b$``
hash whose salt field is too short makes bcrypt < 4.3.0 index past the end of
a slice inside its Rust extension; pyo3 converts that panic into
``PanicException``, which derives from ``BaseException`` and therefore walks
straight through the ``except (ValueError, TypeError)`` in
``core.password_hashing``. 4.3.0 raises ``ValueError`` like every other
malformed input. That is the version ``requirements.txt`` pins and the version
CI installs, so the guards below state the dependency instead of assuming it:
a local environment that has drifted off the pin says so in one line rather
than panicking inside a Rust extension and leaving the reader to guess.
"""

import logging
import re
import sys
from pathlib import Path

import bcrypt
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.password_hashing import hash_password, verify_password

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Verified by hand on 4.0.1, 4.1.0, 4.2.0 and 4.2.1 (all panic) and on 4.3.0
# (ValueError), against the exact vector below.
SHORT_SALT_SAFE_FROM = (4, 3, 0)

# A $2b$ hash with a 13-character salt field where 22 are required: the vector
# that panics on every bcrypt before 4.3.0.
SHORT_SALT_HASH = "$2b$12$notavalidhash"
# Full length and correctly shaped, but not a hash of anything. Rejected with
# ValueError by every bcrypt version, so the malformed-input path keeps its
# coverage no matter what is installed.
FULL_LENGTH_INVALID_HASH = "$2b$12$" + "x" * 53


def _pinned_bcrypt_version() -> str:
    """Read the pin rather than restate it, so the two cannot drift apart."""
    for line in (BACKEND_DIR / "requirements.txt").read_text().splitlines():
        match = re.fullmatch(r"\s*bcrypt==([0-9][^\s#]*)\s*", line)
        if match:
            return match.group(1)
    raise AssertionError("backend/requirements.txt no longer pins bcrypt==<version>")


def _version_tuple(raw: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", raw))


def _short_salt_hash() -> str:
    """The panic vector, handed over only to a bcrypt that survives it."""
    if _version_tuple(bcrypt.__version__) < SHORT_SALT_SAFE_FROM:
        pytest.fail(
            f"installed bcrypt {bcrypt.__version__} panics inside its Rust extension on a "
            f"short bcrypt salt instead of raising ValueError (fixed in "
            f"{'.'.join(str(p) for p in SHORT_SALT_SAFE_FROM)}). This environment does not "
            f"match backend/requirements.txt (bcrypt=={_pinned_bcrypt_version()}), which is "
            "what CI and the production image install. Reinstall with: pip install -r "
            "backend/requirements.txt -c backend/constraints.txt"
        )
    return SHORT_SALT_HASH


# Generated with real passlib 1.7.4 + bcrypt 4.3.0 inside python:3.11-slim,
# i.e. exactly the format already in the production users.hashed_password
# column. PASSLIB_MULTIBYTE_SPLIT's plaintext puts the 72-byte truncation
# boundary inside a multibyte character.
PASSLIB_ASCII_SHORT = (
    "$2b$12$lDtZHNmGSvDEPlescHop1.hBlAs5LBeOvHi86ZhiB9WoMqRVuYwMS"  # "Test12345!" (10 bytes)
)
PASSLIB_ASCII_OVER_72 = (
    "$2b$12$s4yoVNIULd4qF.OyRTbmxeGV63Gj1uZijOVx9PV7gaj4rf1tq6sb6"  # "x" * 100 (100 bytes)
)
PASSLIB_MULTIBYTE_SPLIT = (
    "$2b$12$s8gMepzOLPXVJCnUmHwUMe8dO/vhI/E3m9X6a3/h/E8Bc7NTlgyOy"  # "a"*68 + "\u00e9"*6 (80 bytes)
)

# Captured on python:3.11-slim running passlib's os_crypt backend, the era
# before the bcrypt package was declared: the format already sitting in the
# production users.hashed_password column.
LEGACY_OS_CRYPT_HASH = (
    "$2b$12$CZimhXaSWFTXv84OmAnCa.8ikBnq0Ye0amscOXoTRMCs1LX2nFzfq"  # bcrypt of "Test12345!"
)

LEGACY_VECTORS = [
    (PASSLIB_ASCII_SHORT, "Test12345!"),
    (PASSLIB_ASCII_OVER_72, "x" * 100),
    (PASSLIB_MULTIBYTE_SPLIT, "a" * 68 + "\u00e9" * 6),
    (LEGACY_OS_CRYPT_HASH, "Test12345!"),
]


def test_legacy_hashes_from_every_era_still_verify():
    # The two over-72-byte vectors prove the truncation parity: passlib cut
    # the UTF-8 secret at 72 bytes before hashing, and _prepare does the same.
    # If this test ever fails, users with long passwords can no longer log in.
    for hashed, plaintext in LEGACY_VECTORS:
        assert verify_password(plaintext, hashed), hashed
        assert not verify_password("WrongPassword1!", hashed), hashed


def test_round_trip_hash_and_verify():
    hashed = hash_password("CorrectHorse9!")
    # Assert the full $2b$12$ prefix, not just $2b$, so a silent cost change
    # away from the 12 every stored hash uses is caught.
    assert hashed.startswith("$2b$12$")
    assert verify_password("CorrectHorse9!", hashed)
    assert not verify_password("WrongHorse9!", hashed)


def test_bcrypt_ignores_input_past_72_bytes():
    long_password = "y" * 80
    truncated = long_password.encode("utf-8")[:72].decode("ascii")
    hashed = hash_password(long_password)
    # Documents the truncation rather than hiding it: the stored hash is
    # indistinguishable from one of the 72-byte prefix.
    assert verify_password(truncated, hashed)
    assert verify_password(long_password, hashed)


def test_installed_bcrypt_matches_the_pin():
    # SIGV2-1212: the local suite panicked where CI passed, and the whole
    # difference was an environment two minor versions behind the pin. An
    # assertion costs nothing and names the drift the moment it appears.
    pinned = _pinned_bcrypt_version()
    assert bcrypt.__version__ == pinned, (
        f"bcrypt {bcrypt.__version__} is installed but backend/requirements.txt pins "
        f"{pinned}. CI and the production image install the pin, so results from this "
        "environment do not transfer. Reinstall with: pip install -r "
        "backend/requirements.txt -c backend/constraints.txt"
    )


def test_verify_password_never_raises_on_malformed_hashes():
    # Legacy columns can hold non-bcrypt values (fixtures carry "x") and a
    # missing hash must not turn a login into a 500.
    for bad in (None, "", "x", FULL_LENGTH_INVALID_HASH, _short_salt_hash()):
        assert verify_password("anything", bad) is False


def test_malformed_hash_logs_a_warning_without_secrets(caplog):
    # Observability, not silence: a malformed hash must surface in logs so a
    # systematic checkpw failure is visible, but the password and the stored
    # hash (attacker-influenced input) must never be logged.
    password = "Sup3rSecret!"
    malformed = _short_salt_hash()
    with caplog.at_level(logging.WARNING, logger="core.password_hashing"):
        assert verify_password(password, malformed) is False
    assert "malformed hash" in caplog.text
    assert password not in caplog.text
    assert malformed not in caplog.text


def test_non_ascii_password_round_trips():
    hashed = hash_password("pässwörd-密码-🔑")
    assert verify_password("pässwörd-密码-🔑", hashed)
    assert not verify_password("pässwörd-密码", hashed)

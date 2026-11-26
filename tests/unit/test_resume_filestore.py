"""The file store keeps uploads outside the repository under random keys."""
import pytest

from app.rmg.resume.filestore import FileStore


def test_a_file_can_be_stored_and_read_back_by_its_key(tmp_path):
    store = FileStore(tmp_path / "files")

    key = store.put(b"hello", ".docx")

    assert key.endswith(".docx") and store.get(key) == b"hello" and (tmp_path / "files" / key).exists()


def test_two_files_never_share_a_key(tmp_path):
    store = FileStore(tmp_path)

    assert store.put(b"a", ".txt") != store.put(b"a", ".txt")


@pytest.mark.parametrize("key", ["../secret.docx", "..\\secret.docx", "abc.docx", "", "0" * 32 + ".exe", "0" * 32 + ".docx/../x"])
def test_a_key_that_is_not_one_we_made_cannot_reach_any_file(tmp_path, key):
    (tmp_path / "secret.docx").write_bytes(b"secret")

    with pytest.raises(FileNotFoundError):
        FileStore(tmp_path / "files").get(key)


def test_only_known_file_types_are_stored(tmp_path):
    with pytest.raises(ValueError):
        FileStore(tmp_path).put(b"x", ".exe")


def test_a_file_can_be_deleted_and_deleting_twice_is_harmless(tmp_path):
    store = FileStore(tmp_path)
    key = store.put(b"x", ".pdf")

    store.delete(key)
    store.delete(key)

    with pytest.raises(FileNotFoundError):
        store.get(key)


def test_a_badge_picture_can_be_stored_and_a_key_with_another_picture_type_is_still_refused(tmp_path):
    store = FileStore(tmp_path)

    key = store.put(b"png bytes", ".png")

    assert key.endswith(".png") and store.get(key) == b"png bytes"
    with pytest.raises(ValueError):
        store.put(b"x", ".gif")
    with pytest.raises(FileNotFoundError):
        store.get("0" * 32 + ".gif")

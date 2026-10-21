"""Regression tests for the pyOneNote compatibility patches."""

import struct
from io import BytesIO
from types import SimpleNamespace

import pytest
from pyOneNote.FileNode import FileNode, FileNodeList

from onenote_export.parser.one_store import PropertySet


class _Property:
    """Minimal PropertyID stand-in for PropertySet.get_properties()."""

    def __init__(self, name: str, property_type: int) -> None:
        self.name = name
        self.type = property_type

    def __str__(self) -> str:
        return self.name


def _property_set(name: str, value: object, property_type: int) -> PropertySet:
    prop_set = object.__new__(PropertySet)
    prop_set._formated_properties = None
    prop_set.cProperties = 1
    prop_set.rgPrids = [_Property(name, property_type)]
    prop_set.rgData = [value]
    return prop_set


@pytest.mark.parametrize("value", [True, False])
def test_boolean_time_property_is_formatted_as_boolean(value):
    prop_set = _property_set("IsTitleTime", value, 0x02)

    assert prop_set.get_properties() == {"IsTitleTime": str(value)}


def test_ordinary_boolean_property_is_formatted_as_boolean():
    prop_set = _property_set("IsTitleText", True, 0x02)

    assert prop_set.get_properties() == {"IsTitleText": "True"}


def test_four_byte_time_property_keeps_existing_conversion():
    value = struct.pack("<I", 0)
    prop_set = _property_set("CreationTimeStamp", value, 0x05)

    assert prop_set.get_properties() == {
        "CreationTimeStamp": str(PropertySet.time32_to_datetime(0))
    }


def test_eight_byte_time_property_keeps_existing_conversion():
    value = struct.pack("<Q", 0)
    prop_set = _property_set("LastModifiedTime", value, 0x06)

    assert prop_set.get_properties() == {
        "LastModifiedTime": str(PropertySet.parse_filetime(0))
    }


def test_unsupported_time_bytes_are_preserved_as_hex():
    value = b"\x01\x02"
    prop_set = _property_set("CreationTimeStamp", value, 0x04)

    assert prop_set.get_properties() == {"CreationTimeStamp": value.hex()}


def test_non_byte_time_value_is_stringified():
    prop_set = _property_set("CreationTimeStamp", "unknown", 0x07)

    assert prop_set.get_properties() == {"CreationTimeStamp": "unknown"}


def test_formatted_properties_are_cached():
    prop_set = _property_set("IsTitleTime", True, 0x02)

    first = prop_set.get_properties()
    prop_set.rgData[0] = False
    second = prop_set.get_properties()

    assert first is second
    assert second == {"IsTitleTime": "True"}


def _reference(stp: int, cb: int) -> SimpleNamespace:
    return SimpleNamespace(stp=stp, cb=cb)


def _empty_fragment() -> bytes:
    """Build a valid empty FileNodeListFragment with an fcrNil successor."""
    return b"\0" * 16 + struct.pack("<QI", 0xFFFFFFFFFFFFFFFF, 0) + b"\0" * 8


class _SeekRecorder:
    def __init__(self) -> None:
        self.offsets: list[int] = []

    def seek(self, offset: int) -> None:
        self.offsets.append(offset)
        raise RuntimeError("delegated FileNodeList parse")


def test_fcr_zero_is_an_empty_child_file_node_list():
    file = _SeekRecorder()

    child_list = FileNodeList(file, object(), _reference(0, 0))

    assert child_list.end == 0
    assert child_list.fragments == []
    assert file.offsets == []


def test_non_empty_file_node_list_still_delegates_to_pyonenote():
    file = BytesIO(_empty_fragment())

    child_list = FileNodeList(file, object(), _reference(0, 36))

    assert child_list.end == 36
    assert len(child_list.fragments) == 1


@pytest.mark.parametrize(
    "reference",
    [
        _reference(0xFFFFFFFFFFFFFFFF, 0),  # fcrNil
        _reference(0, 1),
        _reference(1, 0),
    ],
)
def test_non_fcr_zero_references_are_delegated(reference):
    file = _SeekRecorder()

    with pytest.raises(RuntimeError, match="delegated"):
        FileNodeList(file, object(), reference)

    assert file.offsets == [reference.stp]


def test_malformed_non_empty_reference_still_raises():
    with pytest.raises(struct.error):
        FileNodeList(BytesIO(b""), object(), _reference(0, 1))


def test_malformed_terminator_node_remains_empty():
    # BaseType 2 makes the dependency attempt to recurse through missing data;
    # the existing compatibility patch must continue to absorb that terminator.
    node = FileNode(BytesIO(struct.pack("<I", 2 << 27)), object())

    assert node.data is None
    assert node.children == []

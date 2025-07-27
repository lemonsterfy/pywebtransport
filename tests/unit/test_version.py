"""Unit tests for the pywebtransport.version module."""

from typing import Tuple

import pytest
from pytest_mock import MockerFixture

from pywebtransport import version as version_module


class TestVersionModule:
    def test_metadata_constants_exist_and_have_correct_types(self) -> None:
        assert isinstance(version_module.__version__, str)
        assert isinstance(version_module.__version_info__, tuple)
        assert isinstance(version_module.__author__, str)
        assert isinstance(version_module.__email__, str)
        assert isinstance(version_module.__license__, str)
        assert isinstance(version_module.__description__, str)
        assert isinstance(version_module.__url__, str)

    def test_derived_constants_are_correct(self) -> None:
        version_info: Tuple[int, int, int] = version_module.__version_info__
        assert version_module.MAJOR == version_info[0]
        assert version_module.MINOR == version_info[1]
        assert version_module.PATCH == version_info[2]

    def test_get_version(self) -> None:
        assert version_module.get_version() == version_module.__version__

    def test_get_version_info__(self) -> None:
        assert version_module.get_version_info__() == version_module.__version_info__

    @pytest.mark.parametrize(
        "mock_major, expected_result",
        [
            (0, False),
            (1, True),
            (2, True),
        ],
    )
    def test_is_stable(self, mocker: MockerFixture, mock_major: int, expected_result: bool) -> None:
        mocker.patch.object(version_module, "MAJOR", mock_major)
        assert version_module.is_stable() is expected_result

    @pytest.mark.parametrize(
        "mock_version_info, expected_result",
        [
            ((0, 1, 0), False),
            ((1, 0, 0), False),
            ((0, 0, 0), True),
        ],
    )
    def test_is_development(
        self, mocker: MockerFixture, mock_version_info: Tuple[int, int, int], expected_result: bool
    ) -> None:
        mocker.patch.object(version_module, "MAJOR", mock_version_info[0])
        mocker.patch.object(version_module, "MINOR", mock_version_info[1])
        mocker.patch.object(version_module, "PATCH", mock_version_info[2])
        assert version_module.is_development() is expected_result

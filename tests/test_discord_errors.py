"""Discord errors must be useful without echoing what the server or the user submitted."""

from fakes import http_error

from clonex.core.discord_errors import (
    http_error_details,
    http_error_message,
    is_name_length_error,
    validation_details,
)

BAD_LENGTH = {"name": {"_errors": [{"code": "BASE_TYPE_BAD_LENGTH", "message": "secret text"}]}}


def test_name_length_is_recognised() -> None:
    assert is_name_length_error(http_error(errors=BAD_LENGTH))


def test_other_fields_are_not_treated_as_a_name_length_problem() -> None:
    both = {**BAD_LENGTH, "color": {"_errors": [{"code": "NUMBER_TYPE_MAX"}]}}
    assert not is_name_length_error(http_error(errors=both))
    assert not is_name_length_error(http_error(status=403, code=50013, errors=BAD_LENGTH))
    assert not is_name_length_error(http_error())


def test_details_expose_paths_and_codes_but_not_api_text() -> None:
    details = http_error_details(http_error(errors=BAD_LENGTH))
    assert "name: BASE_TYPE_BAD_LENGTH" in details
    assert "secret text" not in details


def test_unknown_field_names_and_malformed_codes_are_redacted() -> None:
    errors = {
        "attacker-controlled": {"_errors": [{"code": "lower case <b>value</b>"}]},
        "permission_overwrites": {"0": {"allow": {"_errors": [{"code": "NUMBER_TYPE_MAX"}]}}},
    }
    details = validation_details(http_error(errors=errors))
    assert details == [
        "<unknown field>: VALIDATION_ERROR",
        "permission_overwrites[0].allow: NUMBER_TYPE_MAX",
    ]


def test_detail_output_is_bounded() -> None:
    errors = {str(index): {"_errors": [{"code": "BASE_TYPE_REQUIRED"}]} for index in range(50)}
    assert len(validation_details(http_error(errors=errors))) <= 12


def test_message_states_whether_the_destination_was_touched() -> None:
    assert "partially modified" in http_error_message(http_error(), copy_started=True)
    assert "No destination changes" in http_error_message(http_error(), copy_started=False)

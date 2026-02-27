from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from typer.testing import CliRunner

from canvasctl.cli import (
    VALID_FLOOR_PREFERENCES,
    VALID_ROOM_TYPES,
    _build_room_reservation_url,
    app,
)

runner = CliRunner()

_REQUIRED_ARGS = [
    "rooms", "reserve",
    "--name", "Jane Doe",
    "--email", "jdoe@dons.usfca.edu",
    "--date", "03/15/2026",
    "--start-time", "10:00 AM",
    "--end-time", "12:00 PM",
    "--people", "3",
    "--room-type", "Study Room",
]


class TestBuildRoomReservationUrl:
    def test_required_fields_present(self):
        url = _build_room_reservation_url(
            name="Jane Doe",
            email="jdoe@dons.usfca.edu",
            date="03/15/2026",
            start_time="10:00 AM",
            end_time="12:00 PM",
            num_people=3,
            room_type="Study Room",
            phone=None,
            floor_preference=None,
            notes=None,
        )
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)

        assert qs["entry.1581876510"] == ["Jane Doe"]
        assert qs["entry.517069695"] == ["jdoe@dons.usfca.edu"]
        assert qs["entry.1394121387"] == ["03/15/2026"]
        assert qs["entry.714892402"] == ["10:00 AM"]
        assert qs["entry.1579380649"] == ["12:00 PM"]
        assert qs["entry.1785840432"] == ["3"]
        assert qs["entry.1694640372"] == ["Study Room"]

    def test_optional_fields_omitted_when_none(self):
        url = _build_room_reservation_url(
            name="Jane Doe",
            email="jdoe@dons.usfca.edu",
            date="03/15/2026",
            start_time="10:00 AM",
            end_time="12:00 PM",
            num_people=3,
            room_type="Study Room",
            phone=None,
            floor_preference=None,
            notes=None,
        )
        qs = parse_qs(urlparse(url).query)
        assert "entry.1365170802" not in qs   # phone
        assert "entry.844059824" not in qs    # floor_preference
        assert "entry.784944234" not in qs    # notes

    def test_optional_fields_included_when_provided(self):
        url = _build_room_reservation_url(
            name="Jane Doe",
            email="jdoe@dons.usfca.edu",
            date="03/15/2026",
            start_time="10:00 AM",
            end_time="12:00 PM",
            num_people=2,
            room_type="Classroom",
            phone="415-422-4770",
            floor_preference="4th Floor",
            notes="Need a projector",
        )
        qs = parse_qs(urlparse(url).query)
        assert qs["entry.1365170802"] == ["415-422-4770"]
        assert qs["entry.844059824"] == ["4th Floor"]
        assert qs["entry.784944234"] == ["Need a projector"]

    def test_base_url_is_correct(self):
        url = _build_room_reservation_url(
            name="A", email="a@dons.usfca.edu", date="01/01/2026",
            start_time="9:00 AM", end_time="10:00 AM", num_people=1,
            room_type="Study Room", phone=None, floor_preference=None, notes=None,
        )
        assert url.startswith(
            "https://docs.google.com/forms/d/e/"
            "1FAIpQLSc3VgP92ybtuIe5snk_tw2QQXB8u5VsXDo-CBD_AsRujg6zVw/viewform?"
        )


class TestRoomsReserveCommand:
    def test_no_browser_prints_url(self):
        result = runner.invoke(app, _REQUIRED_ARGS + ["--no-browser"])
        assert result.exit_code == 0
        assert "docs.google.com/forms" in result.output

    def test_url_contains_prefilled_name(self):
        result = runner.invoke(app, _REQUIRED_ARGS + ["--no-browser"])
        assert result.exit_code == 0
        assert "Jane+Doe" in result.output or "Jane%20Doe" in result.output

    def test_url_contains_prefilled_email(self):
        result = runner.invoke(app, _REQUIRED_ARGS + ["--no-browser"])
        assert result.exit_code == 0
        output = result.output.replace("\n", "")
        assert "jdoe%40dons.usfca.edu" in output or "jdoe@dons.usfca.edu" in output

    def test_invalid_room_type_exits_nonzero(self):
        args = [
            "rooms", "reserve",
            "--name", "Jane Doe",
            "--email", "jdoe@dons.usfca.edu",
            "--date", "03/15/2026",
            "--start-time", "10:00 AM",
            "--end-time", "12:00 PM",
            "--people", "3",
            "--room-type", "Hammock Room",
            "--no-browser",
        ]
        result = runner.invoke(app, args)
        assert result.exit_code != 0

    def test_invalid_floor_preference_exits_nonzero(self):
        result = runner.invoke(
            app,
            _REQUIRED_ARGS + ["--floor", "99th Floor", "--no-browser"],
        )
        assert result.exit_code != 0

    def test_all_valid_room_types_accepted(self):
        for room_type in VALID_ROOM_TYPES:
            args = [
                "rooms", "reserve",
                "--name", "Jane Doe",
                "--email", "jdoe@dons.usfca.edu",
                "--date", "03/15/2026",
                "--start-time", "10:00 AM",
                "--end-time", "12:00 PM",
                "--people", "3",
                "--room-type", room_type,
                "--no-browser",
            ]
            result = runner.invoke(app, args)
            assert result.exit_code == 0, f"Failed for room_type={room_type!r}: {result.output}"

    def test_all_valid_floor_preferences_accepted(self):
        for floor in VALID_FLOOR_PREFERENCES:
            result = runner.invoke(
                app,
                _REQUIRED_ARGS + ["--floor", floor, "--no-browser"],
            )
            assert result.exit_code == 0, f"Failed for floor={floor!r}: {result.output}"

    def test_optional_phone_and_notes(self):
        result = runner.invoke(
            app,
            _REQUIRED_ARGS + [
                "--phone", "415-555-1234",
                "--notes", "Need whiteboard access",
                "--no-browser",
            ],
        )
        assert result.exit_code == 0
        assert "415" in result.output

    def test_missing_required_option_exits_nonzero(self):
        result = runner.invoke(app, ["rooms", "reserve", "--name", "Jane Doe"])
        assert result.exit_code != 0

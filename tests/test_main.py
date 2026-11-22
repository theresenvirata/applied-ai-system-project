"""Tests for the command-line demo (src/main.py)."""

from src import main as cli


def test_no_arguments_uses_example_profile():
    assert cli.build_prefs(cli.parse_args([])) == {"genre": "pop", "mood": "happy", "energy": 0.8}


def test_arguments_build_a_profile():
    args = cli.parse_args(["--genre", "lofi", "--mood", "chill", "--energy", "0.35", "--acoustic"])
    assert cli.build_prefs(args) == {"genre": "lofi", "mood": "chill", "energy": 0.35, "likes_acoustic": True}
    assert cli.build_prefs(cli.parse_args(["--no-acoustic"])) == {"likes_acoustic": False}


def test_valid_profile_prints_recommendations(capsys):
    assert cli.main(["--genre", "rock", "--mood", "intense", "--energy", "0.9", "--k", "3"]) == 0
    out = capsys.readouterr().out
    assert "Top 3 Recommendations" in out
    assert "1. Storm Runner" in out


def test_weak_match_prints_notes(capsys):
    assert cli.main(["--genre", "opera", "--mood", "sad", "--acoustic"]) == 0
    out = capsys.readouterr().out
    assert "genre 'opera' is not in the catalog" in out
    assert "no strong matches" in out


def test_invalid_energy_exits_with_error(capsys):
    assert cli.main(["--genre", "pop", "--energy", "5"]) == 2
    assert "energy must be between 0 and 1" in capsys.readouterr().err
    assert cli.main(["--energy", "loud"]) == 2
    assert "must be a number" in capsys.readouterr().err


def test_same_command_gives_same_output(capsys):
    outputs = []
    for _ in range(3):
        cli.main(["--genre", "folk", "--mood", "melancholic", "--energy", "0.3", "--acoustic"])
        outputs.append(capsys.readouterr().out)
    assert outputs[0] == outputs[1] == outputs[2]

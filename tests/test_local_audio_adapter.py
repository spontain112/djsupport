"""Contract tests for the optional local Chromaprint boundary."""

import json
from types import SimpleNamespace

from djsupport.local_audio import ChromaprintLocalAudio
from djsupport.rekordbox import Track


def _track(location: str) -> Track:
    return Track(
        track_id="synthetic-1",
        name="Invented Signal",
        artist="Invented Artist",
        album="",
        remixer="",
        label="",
        genre="",
        date_added="",
        duration=181,
        location=location,
    )


def test_capability_and_observation_use_only_the_selected_audio_reference(tmp_path):
    audio = tmp_path / "selected.wav"
    audio.write_bytes(b"synthetic-not-real-audio")
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if "-version" in command:
            return SimpleNamespace(
                returncode=0, stdout="fpcalc version 1.6.1\n", stderr="",
            )
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "duration": 181.25,
                "fingerprint": "invented-fingerprint-value",
            }),
            stderr="",
        )

    adapter = ChromaprintLocalAudio(executable="fpcalc", runner=run)

    capability = adapter.capability()
    observation = adapter.observe(_track(audio.as_uri()))

    assert capability.available is True
    assert capability.algorithm == "chromaprint"
    assert capability.algorithm_version == "1.6.1"
    assert observation.status == "available"
    assert observation.fingerprint == "invented-fingerprint-value"
    assert observation.duration == 181
    assert commands == [
        ["fpcalc", "-version"],
        ["fpcalc", "-json", str(audio)],
    ]


def test_unavailable_observation_never_exposes_the_private_location(tmp_path):
    private_location = (tmp_path / "private-name.wav").as_uri()
    adapter = ChromaprintLocalAudio(
        executable="fpcalc",
        runner=lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="private-name.wav failed",
        ),
    )

    observation = adapter.observe(_track(private_location))

    assert observation.status == "unavailable"
    assert observation.reason == "missing_file"
    assert "private-name" not in repr(observation)

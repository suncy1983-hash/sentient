"""Voice ID: the prompt says who is talking, from a speaker-recognition sensor — optional, off by default."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sentient.const import DOMAIN
from custom_components.sentient.voice_id import current_voice, voice_line
from custom_components.sentient.websocket import GROUPS

SENSOR = "sensor.speaker"
OPTIONS = {"persona": "Nova", "speakers": [], "quiet_start": "00:00:00", "quiet_end": "00:00:00",
           "voice_agent": "conversation.ai"}
ON = {"voice_id": True, "voice_id_sensor": SENSOR, "voice_id_seconds": 20}


async def _setup(hass: HomeAssistant, **extra) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Nova", unique_id=DOMAIN, data={**OPTIONS, **extra})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _prompt(hass: HomeAssistant) -> str:
    api = await llm.async_get_api(hass, DOMAIN, llm.LLMContext(platform="t", context=None, language="en",
                                                               assistant=None, device_id=None))
    return api.api_prompt


def _heard(hass: HomeAssistant, name: str, ago: float = 0, **attrs) -> None:
    when = (dt_util.now() - timedelta(seconds=ago)).isoformat()
    hass.states.async_set(SENSOR, name, {"time": when, **attrs})


async def test_off_by_default(hass: HomeAssistant) -> None:
    await _setup(hass, voice_id_sensor=SENSOR)
    _heard(hass, "Sanya")
    prompt = await _prompt(hass)
    assert "recognised by voice" not in prompt and "didn't recognise this voice" not in prompt


async def test_names_the_speaker_when_fresh(hass: HomeAssistant) -> None:
    await _setup(hass, **ON)
    _heard(hass, "Sanya", person="person.sanya", score=0.83)
    prompt = await _prompt(hass)
    assert "The person talking to you is Sanya (Home Assistant person: person.sanya), recognised by voice." in prompt
    assert '"my" mean Sanya' in prompt


async def test_old_reading_is_ignored(hass: HomeAssistant) -> None:
    await _setup(hass, **ON)
    _heard(hass, "Sanya", ago=60)
    assert "Sanya" not in await _prompt(hass)


async def test_unrecognised_voice_is_never_guessed(hass: HomeAssistant) -> None:
    await _setup(hass, **ON)
    for unknown in ("ismeretlen", "unknown", ""):
        _heard(hass, unknown)
        prompt = await _prompt(hass)
        assert "didn't recognise this voice: don't guess who is talking" in prompt
    _heard(hass, "Kata", known=False)
    assert "didn't recognise" in await _prompt(hass)


async def test_missing_or_unavailable_sensor_says_nothing(hass: HomeAssistant) -> None:
    assert current_voice(hass, ON) is None
    hass.states.async_set(SENSOR, "unavailable")
    assert current_voice(hass, ON) is None
    assert current_voice(hass, {**ON, "voice_id_sensor": None}) is None


async def test_freshness_without_a_timestamp_uses_when_ha_last_heard(hass: HomeAssistant) -> None:
    """A recogniser that doesn't send a time still counts — HA's own report time is used, which moves
    even when the same name is written twice in a row."""
    hass.states.async_set(SENSOR, "Szofi", {"confidence": 91})
    voice = current_voice(hass, ON)
    assert voice is not None and voice.name == "Szofi" and voice.confidence == 0.91
    later = dt_util.utcnow() + timedelta(seconds=45)
    assert current_voice(hass, ON, now=later) is None
    assert voice_line(hass, {**ON, "voice_id_seconds": 60}, now=later) is not None


async def test_settings_are_in_the_voice_group() -> None:
    voice = next(g for g in GROUPS if g[0] == "voice")[4]
    assert {"voice_id", "voice_id_sensor", "voice_id_seconds"} <= set(voice)

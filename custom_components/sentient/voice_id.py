"""Voice ID: telling the AI who is talking.

Sentient doesn't recognise voices itself. A speaker-recognition service does — one that sits in front of the
speech-to-text in the voice pipeline and, for every request, writes the name of whoever spoke to a sensor just
before the text reaches the agent. When this is on and that sensor was updated a moment ago, the prompt says
who is talking ("me" and "my" then mean them), or that the voice wasn't recognised, so the AI doesn't guess.

A reading older than the set number of seconds is ignored: it belongs to an earlier request, not this one.
No AI calls, nothing stored. Off by default; which sensor and how fresh, in the settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import CONF_VOICE_ID, CONF_VOICE_ID_SECONDS, CONF_VOICE_ID_SENSOR, DEFAULT_VOICE_ID_SECONDS, MAX_VOICE_ID_SECONDS

# what a recogniser writes when it heard someone it doesn't know
UNRECOGNISED = {"", STATE_UNKNOWN, STATE_UNAVAILABLE, "none", "unknown_speaker", "ismeretlen", "inconnu", "unbekannt", "nobody"}


@dataclass(frozen=True)
class Voice:
    name: str | None  # None: someone spoke, but the voice wasn't recognised
    person: str | None = None  # a person.* entity, when the recogniser links one
    confidence: float | None = None


def _when(state) -> datetime:
    """When the recogniser last reported: its own timestamp if it gives one, else when HA last heard from it
    (last_reported moves even when the same name is written twice in a row)."""
    stamp = state.attributes.get("time") or state.attributes.get("timestamp")
    if isinstance(stamp, str) and (parsed := dt_util.parse_datetime(stamp)) is not None:
        return dt_util.as_utc(parsed)
    return getattr(state, "last_reported", None) or state.last_updated


def current_voice(hass: HomeAssistant, opts: dict[str, Any], now: datetime | None = None) -> Voice | None:
    """Who is talking right now, or None when that isn't known (off, no sensor, or the reading is old)."""
    if not opts.get(CONF_VOICE_ID) or not (entity_id := opts.get(CONF_VOICE_ID_SENSOR)):
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state == STATE_UNAVAILABLE:
        return None
    seconds = min(max(float(opts.get(CONF_VOICE_ID_SECONDS) or DEFAULT_VOICE_ID_SECONDS), 1), MAX_VOICE_ID_SECONDS)
    if (now or dt_util.utcnow()) - _when(state) > timedelta(seconds=seconds):
        return None
    name = str(state.state).strip()
    if name.lower() in UNRECOGNISED or state.attributes.get("known") is False:
        return Voice(None)
    person = state.attributes.get("person")
    person = person if isinstance(person, str) and person.startswith("person.") else None
    score = state.attributes.get("score", state.attributes.get("confidence"))
    try:
        confidence = float(score) if score is not None else None
    except (TypeError, ValueError):
        confidence = None
    if confidence is not None and confidence > 1:
        confidence /= 100  # a percentage
    return Voice(name, person, confidence)


def voice_line(hass: HomeAssistant, opts: dict[str, Any], now: datetime | None = None) -> str | None:
    """The prompt line about who is talking, or None to say nothing."""
    voice = current_voice(hass, opts, now)
    if voice is None:
        return None
    if voice.name is None:
        return ("The house didn't recognise this voice: don't guess who is talking. If it matters (someone's "
                "reminder, list or memory), ask who it is.")
    person = f" (Home Assistant person: {voice.person})" if voice.person else ""
    return (f"The person talking to you is {voice.name}{person}, recognised by voice. \"I\", \"me\" and \"my\" "
            f"mean {voice.name}. Use their name only when it's natural.")

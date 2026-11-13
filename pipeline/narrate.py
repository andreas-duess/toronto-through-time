"""The story read aloud: web/public/audio/<key>.mp3 for every stop of data/manual/story.csv, and
web/public/data/narration.json, which says which file belongs to which stop.

The voice is "David Baker" from ElevenLabs' voice library (text to speech; the key is in ~/.config/secrets/ELEVENLABS_API_KEY).
A file is named after its text, so only stops whose text changed are made again.

A few stops have a sound under the voice (the `sound` column of story.csv): web/public/audio/fx-<name>.mp3,
made once with ElevenLabs' sound effects from the descriptions in SOUNDS, 20 seconds each, played
quietly and in a loop by the page. One sound is a real recording, not made here: fx-lastpost.mp3, the Last
Post played on a bugle (Sgt. Codie Lynn Williams, U.S. Marine Corps; public domain; Wikimedia Commons,
"Last Post bugle call.ogg"), cut to 80 seconds.

Run: uv run pipeline/narrate.py
"""
import csv
import hashlib
import json
import pathlib
import re
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
AUDIO = ROOT / "web" / "public" / "audio"
VOICE = "fxnZk29PIJ3WKEC9MDEo"     # David Baker: a calm, mature Canadian narrator
MODEL = "eleven_multilingual_v2"
SOUNDS = {
    "battle": "A distant battle in 1813: scattered musket volleys and a few cannon shots across open ground, no voices, no music",
    "fire": "A large city fire at night: timber crackling and roaring flames, distant men shouting, a fire bell ringing far away, no music",
    "train": "Close recording of an old steam locomotive pulling a train at walking pace: slow heavy rhythmic chuff, chuff, chuff, chuff of the engine and iron wheels clanking over rail joints. No whistle, no horn, no siren, no bell, no hiss, no music",
    "fair": "A busy outdoor country fair in the 1870s: a happy crowd milling about, hand bells ringing, a barker calling out, farm animals in the distance, no music, no modern sounds",
    "boo": "A crowd of men loudly booing in unison: long drawn-out boooo, boooo, disapproving jeers, thumbs down, in a large hall. Only booing, no cheering, no applause, no laughter, no music",
    "building": "Year 1793, men building log cabins by hand in a forest clearing: axes chopping wood, wooden mallets knocking, logs being dropped, men shouting orders and calling to each other throughout. Hand tools only. No saws of any kind, no engines, no motors, no machines, no electric tools, no music",
    "bell": "A single church bell tolling slowly for a funeral, one deep toll every three seconds, outdoors, quiet, no other sounds, no music",
    "toast": "A room full of people in a tavern in the 1860s cheering together and clinking glasses, a hearty cheer, laughter, no music, no modern sounds",
    "storm": "A violent storm on a lake shore: strong wind and heavy waves breaking on sand, no thunder, no music",
    "cheer": "A crowd of a few hundred people cheering and applauding outdoors in a town square in the 1830s, hats in the air, no music, no modern sounds",
    "hooves": "Horses' hooves walking on a cobbled city street pulling a streetcar on rails, a small bell now and then, no voices, no music",
}

ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "- - twenty thirty forty fifty sixty seventy eighty ninety".split()


def words(n):
    """A whole number under a million in words: 6200 -> "six thousand two hundred". Written as
    "6,200" the voice read it as "six, two hundred"."""
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("-" + ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return ONES[n // 100] + " hundred" + (" and " + words(n % 100) if n % 100 else "")
    return words(n // 1000) + " thousand" + (" " + words(n % 1000) if n % 1000 else "")


if __name__ == "__main__":
    key = (pathlib.Path.home() / ".config" / "secrets" / "ELEVENLABS_API_KEY").read_text().strip().split("=")[-1]
    AUDIO.mkdir(parents=True, exist_ok=True)
    files, made = [], 0
    for stop in csv.DictReader((ROOT / "data" / "manual" / "story.csv").open()):
        # the headline is on the card; the voice reads the text only, with large numbers in words
        said = re.sub(r"\b\d{1,3}(?:,\d{3})+\b", lambda m: words(int(m.group().replace(",", ""))), stop["text"])
        name = hashlib.sha1(f"{VOICE}|{MODEL}|{said}".encode()).hexdigest()[:12] + ".mp3"
        files.append(name)
        if (AUDIO / name).exists():
            continue
        body = json.dumps({"text": said, "model_id": MODEL, "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}).encode()
        req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}?output_format=mp3_44100_64", body,
                                     {"xi-api-key": key, "content-type": "application/json"})
        (AUDIO / name).write_bytes(urllib.request.urlopen(req, timeout=120).read())
        made += 1
        print("made", name, stop["title"], flush=True)
    for name, description in SOUNDS.items():
        if (AUDIO / f"fx-{name}.mp3").exists():
            continue
        body = json.dumps({"text": description, "duration_seconds": 20, "prompt_influence": 0.5}).encode()
        req = urllib.request.Request("https://api.elevenlabs.io/v1/sound-generation?output_format=mp3_44100_64", body,
                                     {"xi-api-key": key, "content-type": "application/json"})
        (AUDIO / f"fx-{name}.mp3").write_bytes(urllib.request.urlopen(req, timeout=180).read())
        print("made sound", name, flush=True)
    for old in AUDIO.glob("*.mp3"):
        if old.name not in files and not old.name.startswith("fx-"):
            old.unlink()
    (ROOT / "web" / "public" / "data" / "narration.json").write_text(json.dumps(files))
    print(f"{made} made, {len(files)} in all, {sum((AUDIO / f).stat().st_size for f in files) / 1e6:.1f} MB")

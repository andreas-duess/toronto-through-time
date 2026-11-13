"""The story read aloud: web/public/audio/<key>.mp3 for every stop of data/manual/story.csv, and
web/public/data/narration.json, which says which file belongs to which stop.

The voice is ElevenLabs' "George" (text to speech; the key is in ~/.config/secrets/ELEVENLABS_API_KEY).
A file is named after its text, so only stops whose title or text changed are made again.

Run: uv run pipeline/narrate.py
"""
import csv
import hashlib
import json
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
AUDIO = ROOT / "web" / "public" / "audio"
VOICE = "JBFqnCBsd6RMkjVDRZzb"     # George, a storyteller's voice
MODEL = "eleven_multilingual_v2"

if __name__ == "__main__":
    key = (pathlib.Path.home() / ".config" / "secrets" / "ELEVENLABS_API_KEY").read_text().strip().split("=")[-1]
    AUDIO.mkdir(parents=True, exist_ok=True)
    files, made = [], 0
    for stop in csv.DictReader((ROOT / "data" / "manual" / "story.csv").open()):
        said = f"{stop['title']}. {stop['text']}"
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
    for old in AUDIO.glob("*.mp3"):
        if old.name not in files:
            old.unlink()
    (ROOT / "web" / "public" / "data" / "narration.json").write_text(json.dumps(files))
    print(f"{made} made, {len(files)} in all, {sum((AUDIO / f).stat().st_size for f in files) / 1e6:.1f} MB")

# Khmer Dub

Turn a Chinese video into a **Khmer video**:

1. **Removes the Chinese voice** and keeps the music and sound effects (Demucs)
2. **Writes the Chinese transcript** from the speech (Whisper)
3. **Translates it to Khmer**: pick Google (free), Claude, ChatGPT, Gemini or an offline model
4. **Lets you review and fix** every line before dubbing
5. **Dubs it in Khmer** with the **Sreymom** (female) and **Piseth** (male) voices, chosen automatically per line from the original speaker's voice
6. **Adds Khmer subtitles**, burned in or as a separate track
7. **Blurs Chinese text** on screen: subtitles, logos/watermarks, and moving or floating text

Runs on Windows, macOS and Linux, with or without a GPU. Everything runs on your
computer, except Google/Claude/ChatGPT/Gemini translation and the Khmer voices, which need internet.

---

## Quick start (no programming needed)

1. **Download** this project: green **Code** button → **Download ZIP**, then unzip it
   (or `git clone https://github.com/Sokthearith/khmer-dub.git`).
2. **Start it:**
   - **Windows**: double-click `start-windows.bat`
   - **Mac**: double-click `start-mac.command` (first time: right-click → Open)
   - **Linux**: run `./start-mac-linux.sh`
3. The app opens in your browser at <http://localhost:7860>. Keep the black window open while you use it.

The first start takes a while: it installs Python and downloads the AI models (2–4 GB in total).
Later starts are quick. If you have an NVIDIA graphics card, the launchers use it automatically.

## Using the app

1. **Upload** the Chinese video (or pick a project you started before).
2. Choose the **translator** and **voice** settings, then click **Step 1 · Transcribe & translate**.
3. **Review the table.** Fix any Khmer line, and change the voice of a line to `sreymom` or `piseth`
   if the automatic choice is wrong. Click **Save edits**.
4. Optional: open **Blur Chinese text** and click **Make preview** to check a 20-second clip first.
5. Click **Step 2 · Make the Khmer video**, then download the video and the `.srt` subtitles.

Everything is saved in the `projects/` folder. If something stops halfway (or you close the app),
pick the project again and continue: finished steps are not repeated, and after editing a line only
that line's voice is made again.

### Translators

| Translator | Cost | Quality | Needs |
|---|---|---|---|
| Google Translate | free | OK, literal | internet |
| Claude (Anthropic) | ~cents per episode | best, natural spoken Khmer, consistent names | API key from [console.anthropic.com](https://console.anthropic.com) |
| ChatGPT (OpenAI) | ~cents per episode | good | API key from [platform.openai.com](https://platform.openai.com) |
| Gemini (Google AI) | free tier available | good | API key from [aistudio.google.com](https://aistudio.google.com) |
| NLLB offline | free | basic | no internet after a one-time ~2.5 GB download |

Paste the API key into the app, or set `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY`.
The AI translators get the previous lines as context and are told to keep each line short enough to
speak in time. You can type another model name in **Model** (for example a newer one).

ChatGPT, Gemini and NLLB need their optional packages. The launchers don't install them; run this once:

```bash
uv sync --extra cpu --extra all-translators
```

(Use `--extra gpu` instead of `--extra cpu` on a computer with an NVIDIA GPU.) After that, start with
`uv run --extra cpu --extra all-translators khmerdub ui`.

### Blur

- **Automatic (Chinese text only)** scans the video a few times per second, reads the text, and blurs
  only text that contains Chinese characters. English or Khmer text stays sharp.
  - Text that stays in one place (logos, watermarks, the subtitle bar) gets one steady blur.
  - Subtitle lines are blurred while they are on screen.
  - Moving or floating text is tracked and the blur follows it.
- **Manual boxes:** for anything the scan misses, open **Blur Chinese text**, show a frame, move the
  sliders over the text and click **Add box** (optionally only between two times).
- **Scan speed:** *Fast* (2 per second) for long, calm videos, *Careful* (5 per second) for fast-moving text.

The Khmer subtitles are placed at the bottom, on top of the blurred Chinese subtitle bar.

## How long does it take?

Measured on a 12-core laptop **without a GPU**, per 10 minutes of video:

| Step | Time |
|---|---|
| Remove Chinese voice | ~TBD |
| Chinese transcript (Whisper `medium`) | ~TBD |
| Translation (Google) | seconds |
| Khmer voices | ~1 min (needs internet) |
| Scan for Chinese text | ~TBD |
| Make video | ~TBD |

So a **1-hour episode takes roughly TBD on a laptop without a GPU**. With an NVIDIA GPU, voice removal
and the transcript are several times faster. Tip: run Step 1, review, then start Step 2 and let it run.

## Command line

```bash
uv run --extra cpu khmerdub run episode01.mp4                      # everything with default settings
uv run --extra cpu khmerdub run episode01.mp4 --stage prepare      # transcript + translation only
#   ...edit episode01_khmerdub/segments.json ...
uv run --extra cpu khmerdub run episode01.mp4 --stage produce      # voices + final video
uv run --extra cpu khmerdub run episode01.mp4 --translator claude --voice auto --blur chinese
uv run --extra cpu khmerdub run episode01.mp4 --blur-region 0,0.82,1,0.15   # extra box: x,y,w,h (0-1)
uv run --extra cpu khmerdub run episode01.mp4 --preview 300        # 20 s preview from 5:00
uv run --extra cpu khmerdub run --help                             # all options
```

Other useful options: `--zh-srt file.srt` (use existing Chinese subtitles instead of speech recognition),
`--km-srt file.srt` (dub an existing Khmer subtitle file), `--keep-chinese-voice` (lower it instead of
removing it), `--subtitles soft|none`, `--whisper-model large-v3`, `--max-speedup 1.3`.

## How it works

```
video ─► audio ─► Demucs ─┬─► vocals ─► Whisper (Chinese transcript) ─► translator (Khmer) ─► review
                          │                └─► pitch ─► Sreymom / Piseth per line
                          └─► music + effects ─────────────────────────────┐
review ─► Edge TTS Khmer voices ─► fit to timing (speed up ≤1.5×) ─► mix ──┴─► final video
video ─► RapidOCR text scan ─► tracks (still / moving) ─► blur ──► + Khmer subtitles (libass) ─┘
```

Project layout: `src/khmerdub/` has one module per step (`separate`, `transcribe`, `translate`,
`voices`, `tts`, `mix`, `subtitles`, `blur`, `render`), plus `pipeline.py` (order and caching),
`cli.py` and `ui.py` (web app).

## Troubleshooting

- **"API key is missing or wrong"**: paste the key for the translator you picked, or switch to Google.
- **Khmer voice step fails**: the Sreymom/Piseth voices come from Microsoft's online Edge read-aloud
  service and need internet. Run Step 2 again; it continues where it stopped.
- **Wrong voice (male/female) on some lines**: fix them in the table (`sreymom` / `piseth`), or choose
  "All Sreymom" / "All Piseth".
- **Some Chinese text is not blurred**: use *Careful* scan, or add a manual box.
- **Subtitles show as a separate track instead of burned in**: your ffmpeg has no subtitle renderer.
  Install ffmpeg from <https://ffmpeg.org> (the app uses it when it is installed).

## Credits

[faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT) ·
[Demucs](https://github.com/facebookresearch/demucs) (MIT) ·
[edge-tts](https://github.com/rany2/edge-tts) (LGPL-3.0) ·
[RapidOCR](https://github.com/RapidAI/RapidOCR) / PaddleOCR models (Apache-2.0) ·
[Gradio](https://gradio.app) (Apache-2.0) ·
[Noto Sans Khmer](https://github.com/notofonts/khmer) (OFL) ·
ffmpeg.

Only dub and publish videos you have the rights to use.

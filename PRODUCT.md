# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Khmer-speaking video creators and their friends who turn Chinese drama episodes (usually about one hour long) into Khmer-dubbed videos for their Facebook pages, YouTube channels and TikTok. They are not programmers; they run the tool on their own Windows, Mac or Linux laptops, often without a graphics card. They mostly work carefully on one episode at a time: process it, review and fix the Khmer lines, check the blur, then export.

## Product Purpose

Khmer Dub turns a Chinese video into a publishable Khmer video on the user's own computer: it removes the Chinese voice while keeping music and effects, transcribes the Chinese, translates it to Khmer, dubs it with the Sreymom (female) and Piseth (male) voices, adds Khmer subtitles, and blurs Chinese text on screen. Success is a Khmer episode the creator is proud to post, made without paid software or technical help.

## Positioning

A free, local, open-source dubbing studio built specifically for Chinese → Khmer: voices picked per line from the original speaker's pitch, a line-by-line review step where you hear the original and the Khmer side by side, and on-screen Chinese text tracking that follows still, popping and moving text. Generic dubbing services don't target Khmer, don't remove burned-in Chinese text, and don't run on the creator's own laptop.

## Operating Context

- Long sessions: a 1-hour episode takes about 2 hours of processing on a CPU-only laptop; the user starts a step, waits, comes back to review.
- Workflow is a fixed sequence: Upload → Settings → Review (line editor, listen to original and Khmer) → Blur check (click two corners to add boxes, 20 s preview) → Export (MP4, Khmer SRT, Khmer audio, Chinese transcript). Batch mode exists for whole series.
- Runs as a local web app (Gradio) in the browser at localhost, started by double-clicking a launcher; a black console window stays open.
- Outputs are posted to Facebook pages, YouTube channels and TikTok.

## Capabilities and Constraints

- Built with Gradio 6 in Python; the UI is styled through a theme, custom CSS and HTML blocks around Gradio components. Components (file upload, dataframe, audio, video, sliders, radios) are Gradio's and must keep working.
- Voices are fixed: Edge TTS km-KH-SreymomNeural and km-KH-PisethNeural.
- Translators: Google (free), Gemini (free key), OpenRouter/Groq/DeepSeek/Ollama (OpenAI-compatible), Claude, ChatGPT, NLLB offline.
- Must work on Windows, macOS and Linux, light or dark system theme, with no internet needed for the UI itself except the voices and online translators.
- Interface language: English first, with small Khmer hints. Khmer text (subtitles, translations) must render correctly (Noto Sans Khmer / Kantumruy Pro).

## Brand Commitments

- Name: "Khmer Dub" (same as the GitHub repo Sokthearith/khmer-dub).
- Voice names Sreymom and Piseth are part of the product's identity.

## Evidence on Hand

- No logo, screenshots for marketing, testimonials or user counts exist; do not invent any.
- Real measured performance: 10-minute video ≈ 20 minutes on a 12-core CPU-only laptop (README).

## Product Principles

1. The creator stays in control: every Khmer line can be heard, edited and re-voiced before export.
2. Never lose work: every step is saved and resumable, because jobs run for hours.
3. Plain language over settings: sensible presets first, details tucked away.
4. Free and local by default; paid AI services are optional upgrades.
5. Khmer is the product: Khmer text is shown large and legible wherever it appears.

## Accessibility & Inclusion

Non-technical users; many read Khmer more comfortably than English, so Khmer hints accompany key steps. Text must stay readable in both light and dark system themes.

# Connect a free AI model
<!-- tags: model, ollama, mlx, openrouter, groq, gemini, key, api key, offline, cloud, free -->

LOKI thinks with an AI model. All the choices below are free.

## On this computer (private, works offline)

Best if your computer has 16 GB of memory or more, or an Apple Silicon Mac.

1. Open the welcome tour (Settings > General > Show the welcome tour again), or **Settings > Local models**.
2. Press **Set it up for me**. LOKI installs **Ollama** (free, open source) if it is missing, downloads a model that fits your computer and switches to it. This is a one-time download of a few GB.
3. You can keep using LOKI while it downloads.

On a Mac with Apple Silicon, LOKI also finds **MLX** if you installed it.

**If it fails:** the message says why. Common fixes:

- *Not enough disk space* - free up the amount shown, then press the button again.
- *Ollama did not install* - install it yourself from https://ollama.com/download, open it once, then press the button again.
- *No model fits* - your computer is small for local models. Use a free online model instead.

## A free online model (needs internet)

What you ask is sent to that service. Good on any computer.

- **OpenRouter** - press **Sign in with OpenRouter**, sign in (or make a free account) in your browser and approve LOKI. No key to copy. Free models have a daily limit.
- **Groq** - open https://console.groq.com/keys, make a free key (it starts with `gsk_`), paste it into LOKI and press **Connect**.
- **Google Gemini** - open https://aistudio.google.com/apikey, make a free key (it starts with `AIza`), paste it and press **Connect**. Google's free tier may use your prompts to improve its products.

**If a key does not work:** copy it again - all of it, with no spaces - or make a new key. Keys stay on this computer and are never shown again.

## Changing it later

**Settings > Connections** lists every provider. You can switch any of them off, test it, or pick the model LOKI uses. **Settings > Local models** shows the models on this computer.

LOKI never spends money unless you allow paid providers (Settings > General), and then only up to the daily limit you set.

# 3D Tetris (Pygame)

A simple 3D Tetris-style game built with `pygame`.

## Features

- True 3D playfield (`x`, `y`, `z`)
- Falling tetracubes (4-block 3D pieces)
- Plane clear mechanic (clears full `x-z` layers)
- Isometric cube rendering with simple shading
- Score, level, and line tracking

## Install (Astral uv)

```bash
uv sync
```

## Run

```bash
just run
```

If Just is not installed yet, you can still run:

```bash
uv run main.py
```

## Web build (pygbag)

Build the browser version:

```bash
just web-build
```

Build and serve it locally at <http://localhost:8000>:

```bash
just web
```

Without Just:

```bash
uv run python -m pygbag --build --app_name "Oskar Game" --title "Oskar Game" .
uv run python -m pygbag --app_name "Oskar Game" --title "Oskar Game" .
```

The web build runs without the local SQLite leaderboard database.

## Controls

- `Left / Right`: move piece on X axis
- `Up / Down`: move piece on Z axis
- `W / S`: rotate around X axis
- `Q / E`: rotate around Y axis
- `A / D`: rotate around Z axis
- `Space`: hard drop
- `P`: pause
- `R`: restart (when game over)
- `Esc`: quit

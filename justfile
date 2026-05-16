set windows-shell := ["powershell.exe", "-NoProfile", "-Command"]

# Run the game through uv-managed environment.
run:
    uv run main.py

# Sync project dependencies.
sync:
    uv sync

# Build the browser version with pygbag.
web-build:
    uv run python -m pygbag --build --app_name "Oskar Game" --title "Oskar Game" .

# Build and serve the browser version at http://localhost:8000.
web:
    uv run python -m pygbag --app_name "Oskar Game" --title "Oskar Game" .

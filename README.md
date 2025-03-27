# Info
This is the prototype repository for cosmic-cargo

# Setup Instructions
To setup this repository for local development you need to first install pre-commit hooks and create a virtual environment

To setup venv, so this in the root directory
```bash
python3 -m venv .venv
```

Activate the virtual environment
```bash
source .venv/bin/activate
```

Sync dependencies with this repo `requirements.txt`
```bash
python -m pip install --upgrade pip && \
pip install -r requirements.txt
```

To set up pre-commit so that the pre commit hooks run against your code on `git commit` ...
pre-commit should be installed with the requirements already.
```bash
pre-commit install
```

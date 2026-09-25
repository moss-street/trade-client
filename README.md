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

# Trade Client

Run commands from the `trade-client` directory after installing the requirements. Each command logs in first. Set `MARKET_SIM_PASSWORD` to provide the password non-interactively; otherwise, the client prompts for it.

```bash
python -m main.main --email user@example.com sequence \
	--source USD --destination BTC --quantity 1 --side sell --type limit --price 50000
```

The `sequence` command creates a trade, retrieves it, and deletes it. Individual RPC operations are also available:

```bash
python -m main.main --email user@example.com create --source USD --destination BTC --quantity 1 --side sell --price 50000
python -m main.main --email user@example.com get 1
python -m main.main --email user@example.com delete 1
```

Use `--target host:port` to connect to a server other than `127.0.0.1:8080`.

# Installation

## Requirements

- Python 3.12 or later
- [pipx](https://pipx.pypa.io) for isolated installation

## Install

```bash
pipx install git+https://github.com/superkosat/clotho.git
```

## Generate Auth Token

```bash
clotho setup
```

This writes a token to `~/.clotho/config.json`. The token is required by all clients connecting to the gateway.

To regenerate the token:

```bash
clotho setup --force
```

## Install Docs Dependencies (optional)

```bash
pip install "clotho[docs]"
mkdocs serve
```

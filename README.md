# Power BI Analytics Agent

A plug-and-play analytics agent that helps you connect to data, inspect semantic models, review reports, and export PBIX files — all from natural language.

## Features

- **Connect** to CSV, Excel, and SQL Server data sources
- **Inspect** Power BI semantic models (TMDL/PBIP format)
- **Review** report health, structure, and quality
- **Export** to PBIX using pbi-tools

## Prerequisites

- Python 3.10+
- [pbi-tools](https://pbi.tools/) (1.0.0-rc.3 or newer, with TMDL support)
- An [Anthropic API key](https://console.anthropic.com/)

## Quick Start

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/powerbi-analytics-agent.git
cd powerbi-analytics-agent

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Install
pip install -e ".[dev,ui]"

# Configure
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY

# Run interactive chat
pbi-agent chat

# Or use direct commands
pbi-agent inspect ./path/to/your.pbip
pbi-agent review ./path/to/your.pbip
pbi-agent export ./path/to/your.pbip
```

## Architecture

```
User → CLI/Streamlit → Orchestrator → ┬→ Connection Manager → Data Sources
                                       ├→ Model Inspector → TMDL Parser
                                       ├→ Report Reviewer → Validation
                                       ├→ Export Engine → pbi-tools → PBIX
                                       └→ Logging & Validation
```

## Configuration

Edit `config/settings.yaml` for agent settings. Environment variables in `.env` override YAML values.

## Tech Stack

- **LLM**: Claude (Haiku for routing, Sonnet for analysis)
- **Data**: pandas, pyodbc, sqlalchemy
- **CLI**: click + rich
- **Web UI**: Streamlit (optional)
- **Export**: pbi-tools
- **Config**: YAML + dotenv

## License

MIT

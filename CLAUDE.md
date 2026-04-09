# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this app does

Single-file Streamlit app (`app.py`) for tracking private medical visits and invoices. The doctor records visits per clinic (poliambulatorio), tracks POS/cash payments, and monitors invoice status. The app calculates the doctor's net earnings after each clinic's retention percentage and optional 20% withholding tax (ritenuta d'acconto) on POS payments.

## Running the app

```bash
streamlit run app.py
```

Requires `.streamlit/secrets.toml` — copy from `.streamlit/secrets.toml.example` and fill in:
- `APP_PIN` — login PIN
- `GITHUB_TOKEN` — GitHub personal access token with repo read/write
- `GITHUB_REPO` — repo name in `"owner/repo"` format

## Architecture

**Storage:** GitHub is the database. All data lives in the repo itself:
- `data/visits.csv` — visit records
- `data/invoices.csv` — invoice status per clinic/month
- `clinics.json` — clinic configuration (retention %, ritenuta flag)

Reads/writes go through the PyGitHub library (`gh_read` / `gh_write`). Data is cached with `@st.cache_data(ttl=120)` and invalidated via `_clear_cache()` after every write.

**Auth:** PIN-based via `st.secrets["APP_PIN"]`, stored in `st.session_state.authenticated`.

**Pages** (selected via sidebar radio):
- `page_nuova_visita` — form to log a new visit
- `page_report` — monthly report for a single clinic with invoice status checkboxes
- `page_report_globale` — cross-clinic summary table for a given month
- `page_ricerca` — search visits by patient surname
- `page_poliambulatori` — editable table to manage clinic configs

**Earnings formula:**
```
my_pct = 100 - retention_pct
my_pos  = total_pos  * (my_pct / 100)
my_cash = total_cash * (my_pct / 100)
# If ritenuta_acconto is enabled for the clinic:
my_pos  = my_pos * 0.80
```

**`_render_sticky_table`** renders the global report as raw HTML/CSS injected via `st.markdown(..., unsafe_allow_html=True)` to support sticky first column + header and dark/light theme compatibility.

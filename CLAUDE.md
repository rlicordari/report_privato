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

## Work in progress / known issues

### Sidebar auto-close — DA RISOLVERE
La sidebar deve chiudersi automaticamente quando l'utente clicca una voce del menu di navigazione (radio button).

**Storico tentativi:**
- Tentativo 1: JS con `MutationObserver` su `document.body` + click listener persistente sul sidebar → **rotto**: interferiva con tutti i `st.selectbox` dell'app, i dropdown si chiudevano immediatamente all'apertura.
- Tentativo 2 (commit `f28fce5`): JS one-shot iniettato via `components.html` solo al cambio pagina (confronto `_prev_page` in session_state) → **parzialmente rotto**: i dropdown ora funzionano, ma la sidebar non si chiude.

**Vincolo critico:** qualsiasi soluzione NON deve interferire con i `st.selectbox` / dropdown di Streamlit. Il vecchio approccio con listener persistenti o MutationObserver su body rompe i menu a tendina.

**Stato attuale del codice** (righe ~804-820 in `main()`):
```python
_prev = st.session_state.get("_prev_page")
if _prev is not None and _prev != page:
    components.html("""<script>
    try {
        var d = window.parent.document;
        var btn = d.querySelector('[data-testid="collapsedControl"]') ||
                  d.querySelector('[data-testid="stSidebarCollapseButton"]');
        if (btn) setTimeout(function(){ btn.click(); }, 300);
    } catch(e) {}
    </script>""", height=0)
st.session_state._prev_page = page
```

**Ipotesi sul problema attuale:** `components.html` con `height=0` in Streamlit potrebbe non eseguire lo script affidabilmente, oppure i `data-testid` del pulsante di collasso sono cambiati nell'ultima versione di Streamlit. Da verificare i testid corretti nel DOM live.

### Criticità minori già identificate (NON prioritarie, da non toccare)
- `page_ricerca`: sort per data fatto su stringa `dd/mm/yyyy` invece che su datetime → ordine sbagliato (riga 772-773)
- `page_report_globale`: usa `bool()` grezzo invece di `_safe_bool()` per i campi fattura (righe 623-624) → può crashare su NaN
- Dark mode tabella HTML (`_render_sticky_table`): CSS usa `prefers-color-scheme` (OS) invece del tema Streamlit → colori sbagliati se OS e Streamlit non sono allineati

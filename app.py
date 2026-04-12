import streamlit as st
import pandas as pd
import json
import io
from datetime import date, datetime
from github import Github, GithubException

# ─── CONFIG ──────────────────────────────────────────────────────────────────

_sidebar_state = "collapsed" if st.session_state.get("_collapse_sidebar") else "auto"
if st.session_state.get("_collapse_sidebar"):
    st.session_state["_collapse_sidebar"] = False

st.set_page_config(
    page_title="Attività Privata",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state=_sidebar_state,
)

VISITS_FILE   = "data/visits.csv"
CLINICS_FILE  = "clinics.json"
INVOICES_FILE = "data/invoices.csv"

MONTHS_IT = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]

EMPTY_VISITS = pd.DataFrame(
    columns=["data", "poliambulatorio", "nome", "cognome", "pagato_pos", "pagato_cash"]
)
EMPTY_INVOICES = pd.DataFrame(
    columns=["anno", "mese", "poliambulatorio", "fattura_emessa", "fattura_pagata"]
)

# ─── AUTH ────────────────────────────────────────────────────────────────────

def check_auth() -> bool:
    if st.session_state.get("authenticated"):
        return True

    st.markdown("## 🔐 Accesso")
    pin = st.text_input("PIN", type="password", key="pin_input")
    if st.button("Entra", type="primary"):
        if pin == st.secrets.get("APP_PIN", ""):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("PIN errato")
    return False

# ─── GITHUB HELPERS ──────────────────────────────────────────────────────────

def _get_repo():
    g = Github(st.secrets["GITHUB_TOKEN"])
    return g.get_repo(st.secrets["GITHUB_REPO"])


def gh_read(path: str):
    """Returns (content_bytes, sha) or (None, None) if not found."""
    try:
        f = _get_repo().get_contents(path)
        return f.decoded_content, f.sha
    except GithubException:
        return None, None


def gh_write(path: str, content: str, sha: str | None = None, msg: str = "update"):
    """Create or update a file on GitHub."""
    repo = _get_repo()
    # Always fetch latest sha to avoid conflicts
    try:
        existing = repo.get_contents(path)
        repo.update_file(path, msg, content, existing.sha)
    except GithubException:
        repo.create_file(path, msg, content)

# ─── DATA ACCESS ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=120)
def get_clinics() -> list[dict]:
    content, _ = gh_read(CLINICS_FILE)
    if content:
        return json.loads(content.decode("utf-8"))
    return []


@st.cache_data(ttl=120)
def get_visits() -> pd.DataFrame:
    content, _ = gh_read(VISITS_FILE)
    if content and content.strip():
        df = pd.read_csv(io.BytesIO(content))
        return df
    return EMPTY_VISITS.copy()


@st.cache_data(ttl=120)
def get_invoices() -> pd.DataFrame:
    content, _ = gh_read(INVOICES_FILE)
    if content and content.strip():
        df = pd.read_csv(io.BytesIO(content))
        return df
    return EMPTY_INVOICES.copy()


def _clear_cache():
    st.cache_data.clear()


def _safe_bool(val) -> bool:
    """Converte in bool gestendo celle vuote (NaN) nel CSV."""
    try:
        return bool(val) if pd.notna(val) else False
    except Exception:
        return False

# ─── PAGE: NUOVA VISITA ───────────────────────────────────────────────────────

def page_nuova_visita():
    st.title("➕ Nuova Visita")

    clinics = get_clinics()
    if not clinics:
        st.error("Nessun poliambulatorio configurato. Vai in 'Poliambulatori' per aggiungerne.")
        return

    clinic_names = [c["name"] for c in clinics]

    # Selectbox FUORI dal form: clear_on_submit non lo resetta
    last = st.session_state.get("last_clinic", clinic_names[0])
    default_idx = clinic_names.index(last) if last in clinic_names else 0
    poli = st.selectbox("Poliambulatorio *", clinic_names, index=default_idx, key="poli_select")

    with st.form("form_visita", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            data_visita = st.date_input("Data *", value=date.today())
            nome = st.text_input("Nome paziente")
            cognome = st.text_input("Cognome paziente *")

        with col2:
            st.markdown("**Pagamento**")
            pos  = st.number_input("Importo POS (€)",  min_value=0.0, step=10.0, format="%.2f", value=None, placeholder="0.00")
            cash = st.number_input("Importo CASH (€)", min_value=0.0, step=10.0, format="%.2f", value=None, placeholder="0.00")
            totale = (pos or 0) + (cash or 0)
            if totale > 0:
                st.info(f"Totale visita: **€ {totale:.2f}**")

        submitted = st.form_submit_button("💾 Salva Visita", type="primary", use_container_width=True)

    if submitted:
        if not cognome.strip():
            st.error("Il cognome del paziente è obbligatorio.")
            return
        if (pos or 0) == 0 and (cash or 0) == 0:
            st.warning("Attenzione: importo POS e CASH sono entrambi 0.")

        st.session_state.last_clinic = poli

        df = get_visits()
        new_row = {
            "data":            data_visita.isoformat(),
            "poliambulatorio": poli,
            "nome":            nome.strip(),
            "cognome":         cognome.strip(),
            "pagato_pos":      pos or 0,
            "pagato_cash":     cash or 0,
        }
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        # Normalizza tutte le date al formato YYYY-MM-DD prima di salvare
        df["data"] = pd.to_datetime(df["data"], errors="coerce").dt.strftime("%Y-%m-%d")
        gh_write(
            VISITS_FILE,
            df.to_csv(index=False),
            msg=f"Visita: {cognome.strip()} {nome.strip()} @ {poli} ({data_visita})",
        )
        _clear_cache()
        st.success(f"✅ Visita di **{nome.strip()} {cognome.strip()}** salvata!")

# ─── PAGE: REPORT ─────────────────────────────────────────────────────────────

def page_report():
    st.title("📊 Report")

    clinics = get_clinics()
    if not clinics:
        st.error("Nessun poliambulatorio configurato.")
        return

    clinic_names = [c["name"] for c in clinics]
    clinic_map   = {c["name"]: c["retention_pct"] for c in clinics}

    now = datetime.now()

    col1, col2, col3 = st.columns(3)
    with col1:
        years = list(range(2024, now.year + 2))
        year  = st.selectbox("Anno", years, index=years.index(now.year))
    with col2:
        month_name = st.selectbox("Mese", MONTHS_IT, index=now.month - 1)
        month      = MONTHS_IT.index(month_name) + 1
    with col3:
        poli = st.selectbox("Poliambulatorio", clinic_names)

    df = get_visits()

    if df.empty:
        st.info("Nessun dato. Aggiungi prima le visite.")
        return

    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    df = df.dropna(subset=["data"])
    if df.empty:
        st.info(f"Nessuna visita registrata per **{poli}** nel mese di **{month_name} {year}**.")
        return
    mask     = (df["data"].dt.year == year) & (df["data"].dt.month == month) & (df["poliambulatorio"] == poli)
    filtered = df[mask].copy()

    retention_pct = clinic_map.get(poli, 0)
    my_pct        = 100 - retention_pct

    st.markdown(f"### {poli} — {month_name} {year}")
    st.caption(
        f"Il poliambulatorio trattiene il **{retention_pct}%** | "
        f"La tua quota è il **{my_pct}%**"
    )

    n_visits   = len(filtered)
    total_pos  = float(filtered["pagato_pos"].sum())  if not filtered.empty else 0.0
    total_cash = float(filtered["pagato_cash"].sum()) if not filtered.empty else 0.0
    my_pos     = total_pos  * (my_pct / 100)
    my_cash    = total_cash * (my_pct / 100)
    total_inv  = my_pos + my_cash

    # ── Metriche principali
    st.markdown("#### Riepilogo")
    c1, c2, c3 = st.columns(3)
    c1.metric("Visite nel mese", n_visits)
    c2.metric("Totale POS (pazienti)", f"€ {total_pos:.2f}")
    c3.metric("Totale CASH (pazienti)", f"€ {total_cash:.2f}")

    c4, c5 = st.columns(2)
    c4.metric(f"Tua quota POS ({my_pct}%)",  f"€ {my_pos:.2f}")
    c5.metric(f"Tua quota CASH ({my_pct}%)", f"€ {my_cash:.2f}")

    # ── Dettaglio visite
    if not filtered.empty:
        st.markdown("#### Dettaglio visite")
        for idx, row in filtered.iterrows():
            col_a, col_b, col_c, col_d, col_e, col_del = st.columns([2, 2, 2, 1.5, 1.5, 1])
            col_a.write(row["data"].strftime("%d/%m/%Y"))
            col_b.write(row["nome"])
            col_c.write(row["cognome"])
            col_d.write(f"€ {float(row['pagato_pos']):.2f}")
            col_e.write(f"€ {float(row['pagato_cash']):.2f}")
            if col_del.button("🗑️", key=f"del_{idx}", help="Elimina visita"):
                st.session_state.pending_delete = idx
                st.rerun()

        # Conferma eliminazione
        pending = st.session_state.get("pending_delete")
        if pending is not None and pending in filtered.index:
            pending_row = filtered.loc[pending]
            nome_p = f"{pending_row['nome']} {pending_row['cognome']}".strip()
            st.warning(
                f"Eliminare la visita di **{nome_p}** del "
                f"{pending_row['data'].strftime('%d/%m/%Y')}?"
            )
            c_si, c_no = st.columns(2)
            if c_si.button("✅ Sì, elimina", type="primary"):
                full_df = get_visits()
                full_df["data"] = pd.to_datetime(full_df["data"], errors="coerce")
                full_df = full_df.drop(index=pending).reset_index(drop=True)
                full_df["data"] = full_df["data"].dt.strftime("%Y-%m-%d")
                gh_write(
                    VISITS_FILE,
                    full_df.to_csv(index=False),
                    msg=f"Elimina visita: {pending_row['cognome']} {pending_row['nome']} @ {poli} ({pending_row['data'].date()})",
                )
                st.session_state.pending_delete = None
                _clear_cache()
                st.rerun()
            if c_no.button("❌ Annulla"):
                st.session_state.pending_delete = None
                st.rerun()
    else:
        st.info(f"Nessuna visita registrata per **{poli}** nel mese di **{month_name} {year}**.")

    # ── Stato fattura
    st.divider()
    st.markdown("#### 📄 Stato Fattura")

    inv_df = get_invoices()
    inv_mask = (
        (inv_df["anno"].astype(int) == year) &
        (inv_df["mese"].astype(int) == month) &
        (inv_df["poliambulatorio"] == poli)
    )
    existing = inv_df[inv_mask]

    fat_emessa = _safe_bool(existing.iloc[0]["fattura_emessa"]) if not existing.empty else False
    fat_pagata = _safe_bool(existing.iloc[0]["fattura_pagata"]) if not existing.empty else False

    col_a, col_b = st.columns(2)
    with col_a:
        new_emessa = st.checkbox("✅ Fattura emessa", value=fat_emessa, key=f"emessa_{poli}_{month}_{year}")
    with col_b:
        new_pagata = st.checkbox("💰 Poliambulatorio ha pagato", value=fat_pagata, key=f"pagata_{poli}_{month}_{year}")

    if st.button("💾 Salva stato fattura", type="primary"):
        inv_df = get_invoices()  # re-fetch per sicurezza
        inv_mask = (
            (inv_df["anno"].astype(int) == year) &
            (inv_df["mese"].astype(int) == month) &
            (inv_df["poliambulatorio"] == poli)
        )
        if inv_df[inv_mask].empty:
            new_inv = pd.DataFrame([{
                "anno":            year,
                "mese":            month,
                "poliambulatorio": poli,
                "fattura_emessa":  new_emessa,
                "fattura_pagata":  new_pagata,
            }])
            inv_df = pd.concat([inv_df, new_inv], ignore_index=True)
        else:
            inv_df.loc[inv_mask, "fattura_emessa"] = new_emessa
            inv_df.loc[inv_mask, "fattura_pagata"] = new_pagata

        gh_write(
            INVOICES_FILE,
            inv_df.to_csv(index=False),
            msg=f"Fattura {poli} {month:02d}/{year}",
        )
        _clear_cache()
        st.success("Stato fattura aggiornato!")
        st.rerun()

    # ── Andamento nel tempo
    st.divider()
    st.markdown("#### 📈 Andamento nel tempo")

    mesi_range = st.radio(
        "Periodo di analisi",
        [3, 6, 12],
        format_func=lambda x: f"{x} mesi",
        horizontal=True,
        key="trend_range",
    )

    ha_ritenuta = next((c.get("ritenuta_acconto", False) for c in clinics if c["name"] == poli), False)

    # Costruisce la lista di (anno, mese) a ritroso dal mese selezionato
    periods = []
    for i in range(mesi_range - 1, -1, -1):
        m = month - i
        y = year
        while m <= 0:
            m += 12
            y -= 1
        periods.append((y, m))

    trend_rows = []
    for (y, m) in periods:
        mask_t = (df["data"].dt.year == y) & (df["data"].dt.month == m) & (df["poliambulatorio"] == poli)
        sub    = df[mask_t]
        my_p   = float(sub["pagato_pos"].sum())  * (my_pct / 100)
        my_c   = float(sub["pagato_cash"].sum()) * (my_pct / 100)
        if ha_ritenuta:
            my_p = my_p * 0.80
        trend_rows.append({
            "Mese":   pd.Timestamp(year=y, month=m, day=1),
            "POS":    round(my_p, 2),
            "CASH":   round(my_c, 2),
            "Totale": round(my_p + my_c, 2),
        })

    trend_df = pd.DataFrame(trend_rows).set_index("Mese").sort_index()
    st.line_chart(trend_df)

    # Variazione percentuale primo → ultimo mese del periodo
    def _pct(first, last):
        return (last - first) / first * 100 if first != 0 else None

    def _fmt(val):
        if val is None:
            return "n/d"
        return f"{'+'if val >= 0 else ''}{val:.1f}%"

    first, last = trend_rows[0], trend_rows[-1]
    label_from  = f"{MONTHS_IT[periods[0][1] - 1][:3]} {periods[0][0]}"
    label_to    = f"{MONTHS_IT[periods[-1][1] - 1][:3]} {periods[-1][0]}"
    st.caption(f"Variazione **{label_from} → {label_to}**")

    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("Totale", f"€ {last['Totale']:.2f}", _fmt(_pct(first["Totale"], last["Totale"])))
    mc2.metric("POS",    f"€ {last['POS']:.2f}",    _fmt(_pct(first["POS"],    last["POS"])))
    mc3.metric("CASH",   f"€ {last['CASH']:.2f}",   _fmt(_pct(first["CASH"],   last["CASH"])))

# ─── PAGE: GESTIONE POLIAMBULATORI ───────────────────────────────────────────

def page_poliambulatori():
    st.title("🏥 Gestione Poliambulatori")

    st.markdown(
        "Aggiungi, modifica o elimina i poliambulatori. "
        "La colonna **Trattenuta (%)** indica la percentuale che il poliambulatorio "
        "trattiene sul totale pagato dal paziente."
    )

    clinics = get_clinics()
    # Compatibilità: aggiungi ritenuta_acconto se mancante nei dati esistenti
    for c in clinics:
        c.setdefault("ritenuta_acconto", False)
    df = pd.DataFrame(clinics) if clinics else pd.DataFrame(columns=["name", "retention_pct", "ritenuta_acconto"])

    edited = st.data_editor(
        df,
        column_config={
            "name": st.column_config.TextColumn(
                "Nome Poliambulatorio",
                required=True,
                width="large",
            ),
            "retention_pct": st.column_config.NumberColumn(
                "Trattenuta (%)",
                min_value=0,
                max_value=100,
                step=1,
                format="%d",
                help="% che il poliambulatorio trattiene. Es: 25 → a te resta il 75%.",
            ),
            "ritenuta_acconto": st.column_config.CheckboxColumn(
                "Ritenuta d'Acconto (20%)",
                help="Se attivo, sul POS viene applicata la ritenuta d'acconto del 20% in fattura.",
                default=False,
            ),
        },
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="clinics_editor",
    )

    if st.button("💾 Salva modifiche", type="primary"):
        new_clinics = (
            edited.dropna(subset=["name"])
                  .query("name != ''")
                  .to_dict(orient="records")
        )
        for c in new_clinics:
            c["retention_pct"]    = int(c.get("retention_pct") or 0)
            c["ritenuta_acconto"] = bool(c.get("ritenuta_acconto") or False)

        gh_write(
            CLINICS_FILE,
            json.dumps(new_clinics, ensure_ascii=False, indent=2),
            msg="Aggiornamento lista poliambulatori",
        )
        _clear_cache()
        st.success(f"✅ {len(new_clinics)} poliambulatori salvati!")
        st.rerun()

# ─── HELPER: TABELLA HTML CON PRIMA COLONNA E HEADER FISSI ──────────────────

def _render_sticky_table(rows: list[dict]):
    if not rows:
        return
    cols = list(rows[0].keys())
    is_last = [False] * (len(rows) - 1) + [True]   # ultima riga = TOTALE

    header_cells = "".join(f"<th>{c}</th>" for c in cols)

    body_rows = ""
    for row, last in zip(rows, is_last):
        style = " class='totale'" if last else ""
        cells = "".join(f"<td>{row[c]}</td>" for c in cols)
        body_rows += f"<tr{style}>{cells}</tr>"

    html = f"""
<style>
  .gt-wrap {{
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    width: 100%;
    max-height: 70vh;
    overflow-y: auto;
  }}
  .gt-wrap table {{
    border-collapse: collapse;
    font-size: 13px;
    min-width: max-content;
    color: #31333f;
  }}
  .gt-wrap th, .gt-wrap td {{
    border: 1px solid rgba(0,0,0,0.15);
    padding: 6px 10px;
    white-space: nowrap;
    text-align: right;
    background-color: #ffffff;
    color: #31333f;
  }}
  .gt-wrap tbody tr:nth-child(even) td {{
    background-color: #f0f2f6;
  }}
  .gt-wrap tr.totale td {{
    font-weight: bold;
    background-color: #f0f2f6;
    border-top: 2px solid rgba(0,0,0,0.3);
  }}
  /* Header sticky */
  .gt-wrap thead th {{
    position: sticky;
    top: 0;
    background-color: #e8eaf0 !important;
    z-index: 3;
    font-weight: 600;
  }}
  /* Prima colonna sticky */
  .gt-wrap th:first-child,
  .gt-wrap td:first-child {{
    position: sticky;
    left: 0;
    text-align: left;
    z-index: 2;
    box-shadow: 3px 0 5px -1px rgba(0,0,0,0.2);
    min-width: 130px;
    max-width: 150px;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  /* Prima colonna: forza background opaco per ogni tipo di riga */
  .gt-wrap tbody tr:nth-child(odd) td:first-child  {{ background-color: #ffffff !important; }}
  .gt-wrap tbody tr:nth-child(even) td:first-child  {{ background-color: #f0f2f6 !important; }}
  .gt-wrap tr.totale td:first-child                 {{ background-color: #f0f2f6 !important; }}
  .gt-wrap thead th:first-child                     {{ background-color: #e8eaf0 !important; z-index: 4; }}

  /* ── DARK MODE ── */
  @media (prefers-color-scheme: dark) {{
    .gt-wrap table {{ color: #fafafa; }}
    .gt-wrap th, .gt-wrap td {{
      color: #fafafa;
      background-color: #0e1117;
      border-color: rgba(255,255,255,0.12);
    }}
    .gt-wrap tbody tr:nth-child(even) td  {{ background-color: #262730; }}
    .gt-wrap tr.totale td                 {{ background-color: #262730; border-top-color: rgba(255,255,255,0.3); }}
    .gt-wrap thead th                     {{ background-color: #1e2029 !important; }}

    .gt-wrap tbody tr:nth-child(odd) td:first-child  {{ background-color: #0e1117 !important; }}
    .gt-wrap tbody tr:nth-child(even) td:first-child  {{ background-color: #262730 !important; }}
    .gt-wrap tr.totale td:first-child                 {{ background-color: #262730 !important; }}
    .gt-wrap thead th:first-child                     {{ background-color: #1e2029 !important; }}
  }}
</style>
<div class="gt-wrap">
  <table>
    <thead><tr>{header_cells}</tr></thead>
    <tbody>{body_rows}</tbody>
  </table>
</div>
"""
    st.markdown(html, unsafe_allow_html=True)


# ─── PAGE: REPORT GLOBALE ────────────────────────────────────────────────────

def page_report_globale():
    st.title("🌐 Report Globale")

    clinics = get_clinics()
    if not clinics:
        st.error("Nessun poliambulatorio configurato.")
        return

    clinic_map      = {c["name"]: c["retention_pct"]                    for c in clinics}
    ritenuta_map    = {c["name"]: c.get("ritenuta_acconto", False)       for c in clinics}

    now = datetime.now()
    col1, col2 = st.columns(2)
    with col1:
        years = list(range(2024, now.year + 2))
        year  = st.selectbox("Anno", years, index=years.index(now.year))
    with col2:
        month_name = st.selectbox("Mese", MONTHS_IT, index=now.month - 1)
        month      = MONTHS_IT.index(month_name) + 1

    df = get_visits()
    if df.empty:
        st.info("Nessun dato disponibile.")
        return

    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    df = df.dropna(subset=["data"])

    mask     = (df["data"].dt.year == year) & (df["data"].dt.month == month)
    filtered = df[mask].copy()

    inv_df = get_invoices()

    rows = []
    for clinic in clinics:
        name          = clinic["name"]
        retention_pct = clinic["retention_pct"]
        my_pct        = 100 - retention_pct

        sub       = filtered[filtered["poliambulatorio"] == name]
        n_visite  = len(sub)
        tot_pos   = float(sub["pagato_pos"].sum())
        tot_cash  = float(sub["pagato_cash"].sum())
        mia_pos   = tot_pos  * (my_pct / 100)
        mia_cash  = tot_cash * (my_pct / 100)

        # Applica ritenuta d'acconto 20% sulla quota POS se abilitata
        ha_ritenuta = ritenuta_map.get(name, False)
        if ha_ritenuta:
            mia_pos = mia_pos * 0.80

        inv_mask  = (
            (inv_df["anno"].astype(int) == year) &
            (inv_df["mese"].astype(int) == month) &
            (inv_df["poliambulatorio"] == name)
        )
        inv_row      = inv_df[inv_mask]
        fat_emessa   = bool(inv_row.iloc[0]["fattura_emessa"]) if not inv_row.empty else False
        fat_pagata   = bool(inv_row.iloc[0]["fattura_pagata"]) if not inv_row.empty else False

        rows.append({
            "Poliambulatorio":     name,
            "Visite":              n_visite,
            "_mia_pos_num":        round(mia_pos, 2),
            "_mia_cash_num":       round(mia_cash, 2),
            "_ha_ritenuta":        ha_ritenuta,
            "Fattura emessa":      "✅" if fat_emessa else "❌",
            "Fattura pagata":      "✅" if fat_pagata else "❌",
        })

    active = [r for r in rows if r["Visite"] > 0]

    if not active:
        st.info(f"Nessuna visita registrata nel mese di **{month_name} {year}**.")
        return

    clinics_con_ritenuta = [r["Poliambulatorio"] for r in active if r["_ha_ritenuta"]]

    # Costruisce tabella con colonne compatte
    table_rows = []
    for r in active:
        pos_val = f"{r['_mia_pos_num']:.2f}*" if r["_ha_ritenuta"] else f"{r['_mia_pos_num']:.2f}"
        table_rows.append({
            "Ambulatorio": r["Poliambulatorio"],
            "N.":          r["Visite"],
            "POS €":       pos_val,
            "CASH €":      f"{r['_mia_cash_num']:.2f}",
            "Tot. €":      f"{r['_mia_pos_num'] + r['_mia_cash_num']:.2f}",
            "Emessa":      r["Fattura emessa"],
            "Pagata":      r["Fattura pagata"],
        })

    # Riga TOTALE
    table_rows.append({
        "Ambulatorio": "TOTALE",
        "N.":          sum(r["Visite"]        for r in active),
        "POS €":       f"{sum(r['_mia_pos_num']  for r in active):.2f}",
        "CASH €":      f"{sum(r['_mia_cash_num'] for r in active):.2f}",
        "Tot. €":      f"{sum(r['_mia_pos_num'] + r['_mia_cash_num'] for r in active):.2f}",
        "Emessa":      "",
        "Pagata":      "",
    })

    st.markdown(f"### {month_name} {year}")
    _render_sticky_table(table_rows)

    if clinics_con_ritenuta:
        st.caption(
            "* Su **POS** è applicata la Ritenuta d'Acconto del 20% per: "
            + ", ".join(clinics_con_ritenuta) + "."
        )

    # ── Andamento globale nel tempo
    st.divider()
    st.markdown("#### 📈 Andamento globale nel tempo")

    mesi_range = st.radio(
        "Periodo di analisi",
        [3, 6, 12],
        format_func=lambda x: f"{x} mesi",
        horizontal=True,
        key="global_trend_range",
    )

    # Periodi a ritroso dal mese selezionato
    periods = []
    for i in range(mesi_range - 1, -1, -1):
        m = month - i
        y = year
        while m <= 0:
            m += 12
            y -= 1
        periods.append((y, m))

    trend_rows = []
    for (y, m) in periods:
        mask_t = (df["data"].dt.year == y) & (df["data"].dt.month == m)
        sub    = df[mask_t]
        totale_mese = 0.0
        for clinic in clinics:
            name     = clinic["name"]
            my_pct_c = 100 - clinic["retention_pct"]
            csub     = sub[sub["poliambulatorio"] == name]
            my_p     = float(csub["pagato_pos"].sum())  * (my_pct_c / 100)
            my_c     = float(csub["pagato_cash"].sum()) * (my_pct_c / 100)
            if ritenuta_map.get(name, False):
                my_p = my_p * 0.80
            totale_mese += my_p + my_c
        trend_rows.append({
            "Mese":   pd.Timestamp(year=y, month=m, day=1),
            "Totale": round(totale_mese, 2),
        })

    trend_df = pd.DataFrame(trend_rows).set_index("Mese").sort_index()
    st.line_chart(trend_df)

    def _pct(first, last):
        return (last - first) / first * 100 if first != 0 else None

    def _fmt(val):
        if val is None:
            return "n/d"
        return f"{'+'if val >= 0 else ''}{val:.1f}%"

    first_tot = trend_rows[0]["Totale"]
    last_tot  = trend_rows[-1]["Totale"]
    label_from = f"{MONTHS_IT[periods[0][1] - 1][:3]} {periods[0][0]}"
    label_to   = f"{MONTHS_IT[periods[-1][1] - 1][:3]} {periods[-1][0]}"

    st.caption(f"Variazione **{label_from} → {label_to}**")
    mc1, mc2 = st.columns(2)
    mc1.metric("Totale ultimo mese", f"€ {last_tot:.2f}", _fmt(_pct(first_tot, last_tot)))
    mc2.metric("Totale primo mese",  f"€ {first_tot:.2f}")


# ─── PAGE: RICERCA PAZIENTE ──────────────────────────────────────────────────

def page_ricerca():
    st.title("🔍 Ricerca Paziente")

    df = get_visits()
    if df.empty:
        st.info("Nessun dato disponibile.")
        return

    query = st.text_input("Cerca per nome o cognome", placeholder="es. Rossi").strip()

    if not query:
        return

    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    df = df.dropna(subset=["data"])

    mask = (
        df["cognome"].str.contains(query, case=False, na=False) |
        df["nome"].str.contains(query, case=False, na=False)
    )
    results = df[mask].copy()

    if results.empty:
        st.warning(f"Nessun paziente trovato per **{query}**.")
        return

    st.success(f"Trovati **{len(results)}** risultati per «{query}»")

    display = results[["data", "nome", "cognome", "poliambulatorio", "pagato_pos", "pagato_cash"]].copy()
    display["data"]   = display["data"].dt.strftime("%d/%m/%Y")
    display = display.sort_values("data", ascending=False)
    display.columns = ["Data", "Nome", "Cognome", "Poliambulatorio", "POS (€)", "CASH (€)"]

    st.dataframe(display, use_container_width=True, hide_index=True)


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    if not check_auth():
        return

    with st.sidebar:
        st.markdown("# 🏥 Attività Privata")
        st.divider()
        page = st.radio(
            "Navigazione",
            [
                "➕ Nuova Visita",
                "📊 Report per singolo ambulatorio",
                "🌐 Report Globale",
                "🔍 Ricerca Paziente",
                "🏥 Poliambulatori",
            ],
            label_visibility="collapsed",
        )
        st.divider()
        if st.button("🚪 Esci", use_container_width=True):
            st.session_state.authenticated = False
            st.rerun()

    # Chiudi il sidebar dopo navigazione: imposta il flag e forza un rerun,
    # così set_page_config viene richiamato con initial_sidebar_state="collapsed".
    if st.session_state.get("_nav_page") != page:
        st.session_state["_nav_page"] = page
        st.session_state["_collapse_sidebar"] = True
        st.rerun()

    if page == "➕ Nuova Visita":
        page_nuova_visita()
    elif page == "📊 Report per singolo ambulatorio":
        page_report()
    elif page == "🌐 Report Globale":
        page_report_globale()
    elif page == "🔍 Ricerca Paziente":
        page_ricerca()
    elif page == "🏥 Poliambulatori":
        page_poliambulatori()


main()

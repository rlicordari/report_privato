import streamlit as st
import pandas as pd
import json
import io
from datetime import date, datetime
from github import Github, GithubException

# ─── CONFIG ──────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Attività Privata",
    page_icon="🏥",
    layout="wide",
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

# ─── PAGE: NUOVA VISITA ───────────────────────────────────────────────────────

def page_nuova_visita():
    st.title("➕ Nuova Visita")

    clinics = get_clinics()
    if not clinics:
        st.error("Nessun poliambulatorio configurato. Vai in 'Poliambulatori' per aggiungerne.")
        return

    clinic_names = [c["name"] for c in clinics]

    with st.form("form_visita", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            poli = st.selectbox("Poliambulatorio *", clinic_names)
            data_visita = st.date_input("Data *", value=date.today())
            nome = st.text_input("Nome paziente")
            cognome = st.text_input("Cognome paziente *")

        with col2:
            st.markdown("**Pagamento**")
            pos  = st.number_input("Importo POS (€)",  min_value=0.0, step=10.0, format="%.2f")
            cash = st.number_input("Importo CASH (€)", min_value=0.0, step=10.0, format="%.2f")
            totale = pos + cash
            if totale > 0:
                st.info(f"Totale visita: **€ {totale:.2f}**")

        submitted = st.form_submit_button("💾 Salva Visita", type="primary", use_container_width=True)

    if submitted:
        if not cognome.strip():
            st.error("Il cognome del paziente è obbligatorio.")
            return
        if pos == 0 and cash == 0:
            st.warning("Attenzione: importo POS e CASH sono entrambi 0.")

        df = get_visits()
        new_row = {
            "data":            data_visita.isoformat(),
            "poliambulatorio": poli,
            "nome":            nome.strip(),
            "cognome":         cognome.strip(),
            "pagato_pos":      pos,
            "pagato_cash":     cash,
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
        display = filtered[["data", "nome", "cognome", "pagato_pos", "pagato_cash"]].copy()
        display["data"]   = display["data"].dt.strftime("%d/%m/%Y")
        display.columns   = ["Data", "Nome", "Cognome", "POS (€)", "CASH (€)"]
        st.dataframe(display, use_container_width=True, hide_index=True)
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

    fat_emessa = bool(existing.iloc[0]["fattura_emessa"]) if not existing.empty else False
    fat_pagata = bool(existing.iloc[0]["fattura_pagata"]) if not existing.empty else False

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

    # ── Totali generali in cima
    tot_visite   = sum(r["Visite"]        for r in active)
    tot_mia_pos  = sum(r["_mia_pos_num"]  for r in active)
    tot_mia_cash = sum(r["_mia_cash_num"] for r in active)

    st.markdown(f"### {month_name} {year}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Visite totali",    tot_visite)
    c2.metric("Totale quota POS", f"€ {tot_mia_pos:.2f}")
    c3.metric("Totale quota CASH",f"€ {tot_mia_cash:.2f}")
    st.metric("Totale mese", f"€ {tot_mia_pos + tot_mia_cash:.2f}")

    st.divider()

    # ── Card per ogni poliambulatorio
    clinics_con_ritenuta = []
    for r in active:
        name        = r["Poliambulatorio"]
        ha_ritenuta = r["_ha_ritenuta"]
        mia_pos     = r["_mia_pos_num"]
        mia_cash    = r["_mia_cash_num"]
        totale      = mia_pos + mia_cash
        if ha_ritenuta:
            clinics_con_ritenuta.append(name)

        pos_label = f"€ {mia_pos:.2f} *" if ha_ritenuta else f"€ {mia_pos:.2f}"

        with st.container(border=True):
            st.markdown(f"**{name}** &nbsp;&nbsp; `{r['Visite']} {'visita' if r['Visite'] == 1 else 'visite'}`")
            ca, cb, cc = st.columns(3)
            ca.metric("Quota POS",  pos_label)
            cb.metric("Quota CASH", f"€ {mia_cash:.2f}")
            cc.metric("Totale",     f"€ {totale:.2f}")
            fe_col, fp_col = st.columns(2)
            fe_col.markdown(f"Fattura emessa: {r['Fattura emessa']}")
            fp_col.markdown(f"Fattura pagata: {r['Fattura pagata']}")

    if clinics_con_ritenuta:
        st.caption(
            "* Su **Quota POS** è applicata la Ritenuta d'Acconto del 20% per: "
            + ", ".join(clinics_con_ritenuta) + "."
        )


# ─── PAGE: RICERCA PAZIENTE ──────────────────────────────────────────────────

def page_ricerca():
    st.title("🔍 Ricerca Paziente")

    df = get_visits()
    if df.empty:
        st.info("Nessun dato disponibile.")
        return

    cognome_query = st.text_input("Cerca per cognome", placeholder="es. Rossi").strip()

    if not cognome_query:
        return

    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    df = df.dropna(subset=["data"])

    mask    = df["cognome"].str.contains(cognome_query, case=False, na=False)
    results = df[mask].copy()

    if results.empty:
        st.warning(f"Nessun paziente trovato con cognome **{cognome_query}**.")
        return

    st.success(f"Trovati **{len(results)}** risultati per «{cognome_query}»")

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

"""ID-based navigation from ranking tables to detail tabs."""
import json

import streamlit as st


SCHOOL_TABLE_JS = r"""
export default function ({ data, parentElement, setTriggerValue }) {
    const root = parentElement.querySelector('.ranking');
    root.replaceChildren();
    const search = document.createElement('input');
    search.placeholder = '학교 검색';
    search.setAttribute('aria-label', '학교 검색');
    root.append(search);
    const scroll = document.createElement('div');
    scroll.style.overflow = 'auto';
    scroll.style.maxHeight = '480px';
    const table = document.createElement('table');
    scroll.append(table);
    root.append(scroll);
    const head = table.createTHead().insertRow();
    const body = table.createTBody();
    let sortColumn = -1, direction = 1;
    function render() {
        body.replaceChildren();
        const query = search.value.toLocaleLowerCase();
        const rows = data.rows.filter(row => row.values.some(value =>
            String(value ?? '').toLocaleLowerCase().includes(query)));
        if (sortColumn >= 0) rows.sort((a, b) => {
            const x = a.values[sortColumn], y = b.values[sortColumn];
            if (x == null) return y == null ? 0 : 1;
            if (y == null) return -1;
            return direction * (typeof x === 'number' && typeof y === 'number'
                ? x - y : String(x).localeCompare(String(y), 'ko', {numeric: true}));
        });
        for (const row of rows) {
            const tr = body.insertRow();
            tr.tabIndex = 0;
            tr.title = '더블클릭 또는 Enter로 학교 상세 보기';
            const open = () => setTriggerValue('opened', row.id);
            tr.ondblclick = open;
            tr.onkeydown = event => {
                if (event.key === 'Enter') { event.preventDefault(); open(); }
            };
            row.values.forEach((value, index) => {
                const td = tr.insertCell();
                const column = data.columns[index];
                let text = value == null ? '자료 부족' : String(value);
                if (typeof value === 'number') {
                    if (column.includes('순위')) text = value.toFixed(0) + '위';
                    else if (column.includes('률')) text = (value * 100).toFixed(2) + '%';
                    else if (column.includes('백분위')) text = value.toFixed(1) + '%';
                    else text = value.toLocaleString('ko-KR', {maximumFractionDigits: 3});
                }
                td.textContent = text;
            });
        }
    }
    data.columns.forEach((name, index) => {
        const th = document.createElement('th');
        const button = document.createElement('button');
        button.textContent = name;
        button.onclick = () => {
            direction = sortColumn === index ? -direction : 1;
            sortColumn = index;
            for (const cell of head.cells) cell.removeAttribute('aria-sort');
            th.setAttribute('aria-sort', direction === 1 ? 'ascending' : 'descending');
            render();
        };
        th.append(button); head.append(th);
    });
    search.oninput = render;
    render();
}
"""

_school_table = st.components.v2.component(
    "school_detail_table",
    html='<div class="ranking"></div>',
    js=SCHOOL_TABLE_JS,
    css="""
    .ranking {font-family:var(--st-font); color:var(--st-text-color)}
    input {padding:8px; margin-bottom:8px; color:inherit; background:var(--st-background-color); border:1px solid var(--st-border-color); border-radius:6px}
    table {border-collapse:collapse; width:100%; font-size:14px}
    th, td {padding:8px 12px; text-align:left; white-space:nowrap; border-bottom:1px solid var(--st-border-color)}
    th {position:sticky; top:0; background:var(--st-secondary-background-color)}
    button {font:inherit; color:inherit; border:0; background:transparent; cursor:pointer}
    tbody tr {cursor:pointer}
    tbody tr:hover, tbody tr:focus {background:var(--st-secondary-background-color)}
    """,
)


def open_detail(state, entity_id, allowed_ids, tab_key, selection_key, detail_label):
    """Ignore stale/invalid events and retain identity across sorting and filtering."""
    if entity_id not in set(map(str, allowed_ids)):
        return
    state[selection_key] = entity_id
    state[tab_key] = detail_label


def school_ranking_table(view, ids, *, key, tab_key, selection_key):
    ids = list(map(str, ids))
    values = json.loads(view.to_json(orient="values", force_ascii=False))

    def on_open():
        entity_id = st.session_state.get(key, {}).get("opened")
        open_detail(st.session_state, entity_id, ids, tab_key, selection_key, "학교 상세")

    st.caption("학교 행을 더블클릭하면 학교 상세로 이동합니다. 키보드에서는 Enter를 누르세요.")
    _school_table(
        data={"columns": list(view.columns), "rows": [
            {"id": entity_id, "values": row} for entity_id, row in zip(ids, values, strict=True)
        ]},
        key=key, on_opened_change=on_open,
    )


def detail_selection(label, options, id_column, labels, *, key):
    ids = options[id_column].astype(str).tolist()
    if st.session_state.get(key) not in ids:
        st.session_state[key] = ids[0]
    names = dict(zip(ids, labels, strict=True))
    selected = st.selectbox(label, ids, format_func=names.__getitem__, key=key, placeholder="선택")
    return options.iloc[ids.index(selected)]

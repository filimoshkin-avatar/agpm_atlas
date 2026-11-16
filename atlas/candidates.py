"""M-CANDIDATES: review proposals, scoped exclusions and atomic scenario acceptance.

START_MODULE_CONTRACT: no global material changes or automatic publication.
Preview and accept use identical evidence checks; row locks + revision prevent stale
choices; candidate-derived item keys prevent duplicate creation. DEPENDS: rules/editor.
"""

from __future__ import annotations

import hashlib
import json
import re

from atlas import editor, rules

STOP = {
    "агент",
    "агентн",
    "матери",
    "проект",
    "работ",
    "систем",
    "исполь",
    "управл",
    "подгот",
    "созда",
    "самост",
}


def _words(text):
    return {
        w[:6] for w in re.findall(r"[a-zа-яё]{5,}", text.lower()) if w[:6] not in STOP
    }


def refresh(conn):
    """Bounded lexical suggestions, not model decisions. Never undo review decisions."""
    pool = conn.execute(
        "SELECT id,title,summary FROM materials WHERE status='in_atlas' AND cardinality(radar_ids)>0"
    ).fetchall()
    added = 0
    for c in conn.execute(
        "SELECT * FROM candidates WHERE state='pending' ORDER BY id FOR UPDATE"
    ).fetchall():
        candidate_added = 0
        original = conn.execute(
            """INSERT INTO candidate_materials(candidate_id,material_id,evidence,suggestion)
            VALUES (%s,%s,%s,'Исходный материал предложения') ON CONFLICT DO NOTHING""",
            (c["id"], c["material_id"], json.dumps(c["proposal"], ensure_ascii=False)),
        )
        candidate_added += original.rowcount
        words = _words(
            c["proposal"].get("title", "") + " " + c["proposal"].get("what", "")
        )
        ranked = sorted(
            ((len(words & _words(m["title"] + " " + m["summary"])), m) for m in pool),
            key=lambda x: (-x[0], x[1]["id"]),
        )
        for score, m in ranked[:12]:
            if score < 3 or m["id"] == c["material_id"]:
                continue
            result = conn.execute(
                """INSERT INTO candidate_materials(candidate_id,material_id,evidence,suggestion)
                VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (
                    c["id"],
                    m["id"],
                    json.dumps(
                        {
                            "role": "контекст",
                            "grade": "background",
                            "counts": False,
                            "basis": "Подбор по общим словам; связь требует проверки редактором.",
                            "quote": "",
                        },
                        ensure_ascii=False,
                    ),
                    "Подбор по общим словам; не подтверждение сценария",
                ),
            )
            candidate_added += result.rowcount
        if candidate_added:
            conn.execute(
                "UPDATE candidates SET revision=revision+1 WHERE id=%s", (c["id"],)
            )
        added += candidate_added
    return added


def load(conn, cid, *, lock=False):
    c = conn.execute(
        "SELECT * FROM candidates WHERE id=%s" + (" FOR UPDATE" if lock else ""), (cid,)
    ).fetchone()
    if not c:
        raise LookupError("Предложение не найдено")
    rows = conn.execute(
        """SELECT cm.*, m.title, m.url, m.num, m.summary, m.status, m.desc_origin,
        s.text AS source_text FROM candidate_materials cm JOIN materials m ON m.id=cm.material_id
        LEFT JOIN source_texts s ON s.url_norm=m.url_norm WHERE cm.candidate_id=%s ORDER BY m.num,m.id""",
        (cid,),
    ).fetchall()
    return c, rows


def evidence(row, roles):
    d = row["evidence"]
    role = d.get("role", "контекст")
    grade = d.get("grade", "background")
    if role not in roles or grade not in (
        {"confirms", "refutes"} if role == "независимый обзор" else {roles[role]}
    ):
        role, grade = "контекст", "background"
    quote = d.get("quote", "")
    found = (
        bool(quote.strip())
        and " ".join(quote.split()).casefold()
        in " ".join((row["source_text"] or "").split()).casefold()
    )
    counts = bool(d.get("counts")) and rules.counts_allowed(
        role, grade, row["desc_origin"], has_quote=found, origin="candidate"
    )
    basis = (
        d.get("basis")
        or "Материал предложен для сценария; подтверждение не установлено."
    )
    if d.get("counts") and not counts:
        basis += (
            " Не учитывается: роль, сверка источника или цитата не прошли проверку."
        )
    return {
        "role": role,
        "grade": grade,
        "counts": counts,
        "quote": quote if found else "",
        "basis": basis,
    }


def prepare(conn, c, rows, form):
    title, what = form.get("title", "").strip(), form.get("what", "").strip()
    corridor, level = form.get("corridor", ""), form.get("level", "")
    if not title or len(title) > 160 or not what or len(what) > 200:
        raise ValueError("Укажите название до 160 и описание до 200 знаков")
    if corridor not in {"I", "II", "III", "IV"} or level not in {"1", "2", "3", "4"}:
        raise ValueError("Уточните коридор и уровень самостоятельности перед созданием")
    known = {r["material_id"] for r in rows}
    selected = {
        k.removeprefix("include_")
        for k, v in form.items()
        if k.startswith("include_") and v == "yes"
    }
    if not selected or not selected <= known:
        raise ValueError("Выберите хотя бы один материал из предложения")
    roles = {
        r["name"]: r["default_grade"]
        for r in conn.execute("SELECT name,default_grade FROM ref_roles")
    }
    links = []
    for row in rows:
        if row["material_id"] not in selected:
            continue
        if row["status"] != "in_atlas":
            raise ValueError(
                "Выбранный материал больше не входит в Атлас; обновите отбор"
            )
        links.append(
            {"material": row["material_id"], "num": row["num"], **evidence(row, roles)}
        )
    sig = rules.item_signal(
        {"kind": "scenario", "signal_origin": "rule"}, links, previous="claimed"
    )
    result = {
        "title": title,
        "what": what,
        "corridor": corridor,
        "level": int(level),
        "links": links,
        "signal": sig.value,
        "conflict": sig.conflict,
        "revision": c["revision"],
    }
    result["digest"] = hashlib.sha256(
        json.dumps(result, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return result


def _check_revision(c, form):
    if str(c["revision"]) != form.get("revision"):
        raise ValueError(
            "Предложение изменилось. Обновите страницу и повторите проверку"
        )
    if c["state"] != "pending":
        raise ValueError("Предложение уже рассмотрено")


def save(conn, cid, form, actor, *, reject=False):
    c, rows = load(conn, cid, lock=True)
    _check_revision(c, form)
    known = {r["material_id"] for r in rows}
    selected = {
        k.removeprefix("include_")
        for k, v in form.items()
        if k.startswith("include_") and v == "yes"
    }
    if not selected <= known:
        raise ValueError("Неизвестный материал")
    draft = {k: form.get(k, "")[:500] for k in ("title", "what", "corridor", "level")}
    for row in rows:
        conn.execute(
            """UPDATE candidate_materials SET decision=%s,reviewed_by=%s,reviewed_at=now()
            WHERE candidate_id=%s AND material_id=%s""",
            (
                "included" if row["material_id"] in selected else "excluded",
                actor,
                cid,
                row["material_id"],
            ),
        )
    conn.execute(
        """UPDATE candidates SET draft=%s,revision=revision+1,state=%s,reviewed_by=%s,
        reviewed_at=now(),review_note=%s WHERE id=%s""",
        (
            json.dumps(draft, ensure_ascii=False),
            "rejected" if reject else "pending",
            actor,
            form.get("reason", "")[:2000],
            cid,
        ),
    )
    editor._journal(
        conn,
        actor,
        "candidate",
        str(cid),
        "rejected" if reject else "selection",
        None,
        sorted(selected),
        form.get("reason", ""),
    )
    if reject:
        _close_queue(conn, c)


def _close_queue(conn, c):
    conn.execute(
        """UPDATE queue SET resolved_at=now() WHERE kind='кандидат в сценарии'
        AND object_id=%s AND run_id IS NOT DISTINCT FROM %s AND resolved_at IS NULL""",
        (c["material_id"], c["run_id"]),
    )


def accept(conn, cid, form, actor):
    c, rows = load(conn, cid, lock=True)
    if c["state"] == "accepted":
        return c["item_key"]
    _check_revision(c, form)
    prepared = prepare(conn, c, rows, form)
    if prepared["digest"] != form.get("preview_digest"):
        raise ValueError("Сначала проверьте предпросмотр; данные могли измениться")
    # Serialize position allocation without locking unrelated readers.
    conn.execute("LOCK TABLE items IN SHARE ROW EXCLUSIVE MODE")
    if conn.execute(
        "SELECT key FROM items WHERE lower(title)=lower(%s) AND status NOT IN ('retired','merged')",
        (prepared["title"],),
    ).fetchone():
        raise ValueError(
            "Сценарий с таким названием уже есть; используйте существующую карточку"
        )
    key = f"S_candidate_{cid}"
    nums = ", ".join("№ " + str(link["num"]) for link in prepared["links"])
    why = (
        "Есть подтверждение и опровержение; требуется проверка редактором. "
        if prepared["conflict"]
        else ""
    )
    why += "Отобраны материалы: " + nums + ". "
    why += {
        "claimed": "Учитываемых подтверждений или опровержений нет.",
        "confirmed": "Есть учитываемое подтверждение, опровержений нет.",
        "refuted": "Есть учитываемое опровержение, подтверждений нет.",
    }[prepared["signal"]]
    conn.execute(
        """INSERT INTO items(key,kind,corridor,level,title,short,what,why,card_line,signal,signal_origin,status,origin,position)
        VALUES (%s,'scenario',%s,%s,%s,%s,%s,%s,%s,%s,'rule','new',%s,(SELECT coalesce(max(position),-1)+1 FROM items))""",
        (
            key,
            prepared["corridor"],
            prepared["level"],
            prepared["title"],
            prepared["title"],
            prepared["what"],
            why[:400],
            ("Материалы: " + nums)[:114],
            prepared["signal"],
            "editor:" + actor,
        ),
    )
    for pos, link in enumerate(prepared["links"]):
        conn.execute(
            """INSERT INTO links(material_id,item_key,role,grade,counts,basis,quote,origin,pinned,position)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,true,%s)""",
            (
                link["material"],
                key,
                link["role"],
                link["grade"],
                link["counts"],
                link["basis"],
                link["quote"],
                "editor:" + actor,
                pos,
            ),
        )
    save(conn, cid, form, actor)
    conn.execute(
        "UPDATE candidates SET state='accepted',item_key=%s WHERE id=%s", (key, cid)
    )
    _close_queue(conn, c)
    editor._journal(
        conn,
        actor,
        "item",
        key,
        "created",
        None,
        prepared,
        form.get("reason") or "Принято предложение сценария",
    )
    conn.execute(
        "INSERT INTO item_history(item_key,version,signal,note) VALUES (%s,%s,%s,%s)",
        (
            key,
            "candidate-" + str(cid),
            prepared["signal"],
            "Создан редактором; ещё не опубликован",
        ),
    )
    if prepared["conflict"]:
        conn.execute(
            "INSERT INTO queue(kind,object_id,text) VALUES ('конфликт',%s,'Подтверждение и опровержение в новом сценарии')",
            (key,),
        )
    return key

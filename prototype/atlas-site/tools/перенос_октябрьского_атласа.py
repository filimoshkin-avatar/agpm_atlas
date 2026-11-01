# Перенос данных октябрьского атласа (блок atlasData) в модель данных сайта.
# Запуск: python3 tools/перенос_октябрьского_атласа.py <Атлас_базовые_данные_2026-10-09_v1.json> <card_lines.json> <выход.js>
import json, re, sys, collections
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

src, cards_path, out = sys.argv[1:4]
d = json.load(open(src, encoding='utf-8'))
cards = json.load(open(cards_path, encoding='utf-8'))

MONTHS = {'января':1,'февраля':2,'марта':3,'апреля':4,'мая':5,'июня':6,'июля':7,'августа':8,'сентября':9,'октября':10,'ноября':11,'декабря':12}
MO = {'jun':'2026-06','jul':'2026-07','aug':'2026-08','sep':'2026-09','oct':'2026-10'}
TRACK = ('utm_','fbclid','gclid','yclid','mc_','ref','_ga','igshid','spm','si')

def norm_url(u):
    p = urlsplit(u.strip())
    host = p.netloc.lower()
    if host.startswith('www.'): host = host[4:]
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith(TRACK)]
    q.sort()
    path = p.path.rstrip('/') or '/'
    return urlunsplit(('https', host, path, urlencode(q), ''))

def parse_date(s):
    m = re.search(r'(\d{1,2})\s+([а-яё]+)\s+(\d{4})', s)
    if not m: return None
    return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"

PRACTICE_KEYS = {
 'Права ступенями и границы полномочий':'prava-stupenyami','Классы решений и уровни автономии':'klassy-resheniy',
 'Своя учётная запись агента':'uchetnaya-zapis','Надзор людьми':'nadzor','Журнал и доказательства действий':'zhurnal',
 'Изоляция и проверки между агентами в цепочке':'izolyaciya','Испытания и допуск к работе':'ispytaniya',
 'Проверка действия до исполнения':'proverka-do-ispolneniya','Проектный офис для агентов':'ofis-dlya-agentov',
 'Договор о делегировании и роли':'dogovor','Реестр и перепись агентов':'reestr',
 'Подготовка данных и контекста для агента':'dannye-i-kontekst','Владелец агента':'vladelec','Лимиты расходов':'limity',
 'Оценка доверия во время работы':'ocenka-doveriya','Стоп-кран и откат':'stop-kran'}
DS = {'s':'verified','r':'radar','rt':'radar','t':'title','n':'none'}
GRADE = {'good':'confirms','claim':'claims','warm':'warns','stop':'refutes','':'background'}
ROLE_BASIS = {
 'внедрение с именем':'организация-пользователь сама рассказала о применении',
 'независимый обзор':'независимый обзор без описанной методики',
 'опровержение':'независимая проверка или исследование показали сбой',
 'кейс по данным продавца':'клиент назван, результат приводит продавец',
 'продукт':'описание продукта продавцом','обещание':'обещание продавца на будущее','пилот':'пилот без итогов',
 'консалтинг':'оценка консультанта','риск':'описанный риск','проблема':'описанная проблема','пример компании':'пример компании без результата по сценарию',
 'контекст':'фон по теме','перепечатка':'перепечатка другого материала','опрос':'опрос без привязки к сценарию','сводка исследований':'сводка внешних исследований'}
NOT_COUNTED = {('B1_drafts','n117'):'методика обзора не описана, для подтверждения нужна методика'}

materials = []
by_key = {}
for k in d['order']:
    m = d['mats'][k]
    num = int(m['id'].replace('№','').strip())
    pub = None; radar = []; origin = 'none'
    if m['d'].startswith('в радаре'):
        radar = [parse_date(m['d'])]
    else:
        pub = parse_date(m['d']); origin = 'radar'
    mat = {
        'id': f'm{num:06d}', 'num': num, 'radar_ids': [], 'url': m['u'], 'url_norm': norm_url(m['u']),
        'outlet': m['o'], 'title': m['t'], 'title_orig': '', 'summary': m['s'],
        'numbers': [x.strip() for x in m['n'].split(';') if x.strip()], 'takeaway': m['k'],
        'type': m['ty'], 'evidence': m['ev'], 'flags': [m['fl']] if m['fl'] else [],
        'desc_origin': DS[m['ds']], 'section': m['sec'], 'practice': PRACTICE_KEYS.get(m['pr'], '') if m['pr'] else '',
        'perimeter': '', 'pub_date': pub, 'pub_date_origin': origin, 'radar_dates': radar,
        'first_seen': radar[0] if radar else None, 'month': MO[m['mo']], 'status': 'in_atlas',
        'origin': 'manual-2026-10-09'
    }
    materials.append(mat); by_key[k] = mat['id']

items = []; links = []
for key, it in d['items'].items():
    parts = it['where'].split(' · ')
    kind = {'matrix':'scenario','out':'neighbor','loss':'loss'}[it['kind']]
    sub = parts[2] if kind == 'scenario' and len(parts) > 3 else ''
    card = cards.get(key, {})
    items.append({
        'key': key, 'kind': kind, 'corridor': it['cor'] if kind != 'neighbor' else '', 'sub_area': sub, 'level': it['lv'],
        'title': it['title'], 'short': it['short'],
        'card_title': 'На согласования, сверку, ожидание и передачу работы уходит 35–60% времени (сводка McKinsey).' if kind == 'loss' else '',
        'card_line': card.get('line', '') if kind != 'loss' else 'Команда два спринта ждала согласований юристов и безопасности (блог Райффайзен Банка).',
        'what': it['what'], 'why': it['why'],
        'signal': it['sig'] or None, 'signal_origin': 'rule' if it['sig'] else None, 'status': 'active',
        'origin': 'manual-2026-10-09', 'history': [{'version':'2026-10-09','signal': it['sig'] or None, 'note':'перенос октябрьского атласа'}]
    })
    for mk, role, grade in it['mats']:
        g = GRADE[grade]
        counts = g in ('confirms','refutes') and d['mats'][mk]['ds'] == 's' and (key, mk) not in NOT_COUNTED
        basis = NOT_COUNTED.get((key, mk), ROLE_BASIS.get(role, ''))
        links.append({'material': by_key[mk], 'item': key, 'role': role, 'grade': g, 'counts': counts, 'basis': basis, 'origin': 'manual-2026-10-09'})

refs = {
 'sections': [
  {'key':'map','name':'Главная матрица: сценарии проектной работы','short':'Главная матрица','definition':'Что агент делает в проектной работе: кейс, пилот или продукт с описанием работы на проектной функции.'},
  {'key':'neighbor','name':'Соседние территории','short':'Соседние территории','definition':'Применение агентов вне проектов: поддержка клиентов, ИТ и безопасность, продажи, финансы, маркетинг, инвестиции, страхование, фарма, логистика.'},
  {'key':'practice','name':'Практики контроля','short':'Практики контроля','definition':'Как организации управляют агентами: права, надзор, журнал, испытания, допуск, откат.'},
  {'key':'incident','name':'Инциденты','short':'Инциденты','definition':'Сбой, ошибка, атака, утечка или ущерб от действий агента.'},
  {'key':'norm','name':'Нормы и стандарты','short':'Нормы и стандарты','definition':'Законы, регулирование, стандарты, рамки отраслевых организаций.'},
  {'key':'tool','name':'Инструменты и продукты','short':'Инструменты и продукты','definition':'Выпуски и описания продуктов, платформ и протоколов без описания применения.'},
  {'key':'economy','name':'Экономика и деньги','short':'Экономика и деньги','definition':'Цены, расходы, сделки, раунды, денежная оценка эффекта.'},
  {'key':'maturity','name':'Зрелость и опросы','short':'Зрелость и опросы','definition':'Опросы, индексы, модели зрелости, данные о распространённости.'},
  {'key':'background','name':'Фон: тренды, обучение, мероприятия','short':'Фон','definition':'Прогнозы, мнения, обучение, мероприятия, общие обзоры.'}],
 'practices': [{'key':v,'name':k} for k,v in PRACTICE_KEYS.items()],
 'corridors': [
  {'key':'I','name':'Отбор и планирование','sub':'заявки и отбор, планирование, сроки, ресурсы','areas':['входящие заявки и отбор','планирование, сроки, ресурсы']},
  {'key':'II','name':'Контроль и отчётность','sub':'статусы, риски, отчётность и комитеты','areas':['статусы и контроль исполнения','риски и отклонения','отчётность и комитеты']},
  {'key':'III','name':'Исполнение','sub':'задачи команды: код, аналитика, интеграции','areas':['задачи команды: код, аналитика, интеграции']},
  {'key':'IV','name':'Решения и координация','sub':'изменения, решения, передача работы','areas':['изменения и решения','передача работы между командами']}],
 'levels': [
  {'n':4,'name':'Делает сам в границах','sub':'человек смотрит журнал'},
  {'n':3,'name':'Делает с подтверждением','sub':'каждый шаг подтверждает человек'},
  {'n':2,'name':'Готовит','sub':'человек утверждает'},
  {'n':1,'name':'Подсказывает','sub':'человек делает сам'}],
 'signals': {'confirmed':'Подтвердилось','claimed':'Заявлено','refuted':'Не подтвердилось'},
 'signal_rules': {'confirmed':'компания назвала себя или независимый тест с методикой','claimed':'продавец или консультант, проверки нет','refuted':'независимый тест или исследование показали сбой'},
 'grades': {'confirms':'подтверждает','claims':'заявляет','warns':'предупреждает','refutes':'опровергает','background':'фон'},
 'desc_origin': {'verified':'Описание сверено с источником.','radar':'Описание из выпуска радара: страница источника не открылась.','title':'Описание составлено по названию: страница источника не открылась.','none':'Описания нет: в выпуске радара оно не сохранилось, а страница источника не открылась.'},
 'months': [{'key':'2026-06','name':'Июнь'},{'key':'2026-07','name':'Июль'},{'key':'2026-08','name':'Август'},{'key':'2026-09','name':'Сентябрь'},{'key':'2026-10','name':'Октябрь'}],
 'types': sorted(set(m['type'] for m in materials)),
 'evidence': ['сильная','средняя','слабая'],
}

sheet_texts = [
 {'key':'bracket-low','place':'axis-1-3','text':'Подтверждения есть, когда решает человек','condition':'levels_1_3_have_confirmed'},
 {'key':'bracket-high','place':'axis-4','text':'Пока заявления и сбои','condition':'level_4_no_confirmed'},
 {'key':'gap','place':'under-neighbors','text':'Разрыв с проектной работой. Вне проектов агенты уже сами ведут работу в поддержке клиентов и страховании, и компании рассказывают об этом сами; в проектной работе на этом уровне пока {claimed4} и {refuted4}.','condition':'neighbors_confirmed_on_4_and_matrix_not'},
 {'key':'corridor-iv','place':'corridor-IV','text':'Коридор IV обведён пунктиром: там самые большие потери и меньше всего доказательств.','condition':'corridor_iv_weakest'},
 {'key':'empty','place':'legend','text':'Пустая клетка — белое пятно: материалов о таком сценарии нет.','condition':'any_empty_cell'},
]

version = {'id':'2026-10-09','slice':'2026-10-09','title':'Перенос октябрьского атласа','prev':None,
           'radar_range':{'from':'2026-06-07','to':'2026-10-09','issues':125},
           'note':'Первая версия архива: ручная разметка атласа от 9 октября 2026 года перенесена без изменений.'}

out_obj = {'version':version,'refs':refs,'items':items,'materials':materials,'links':links,'sheet_texts':sheet_texts,
           'versions':[{'id':'2026-10-09','date':'2026-10-09','title':'Перенос октябрьского атласа','materials':len(materials),'items':len(items),'summary':'первая версия архива, ручная разметка','state':'current','demo':False}]}
js = 'window.ATLAS_DATA = ' + json.dumps(out_obj, ensure_ascii=False, separators=(',',':')) + ';\n'
open(out, 'w', encoding='utf-8').write(js)
print('materials', len(materials), 'items', len(items), 'links', len(links), 'counted', sum(1 for l in links if l['counts']))
print('dup url_norm', len(materials) - len(set(m['url_norm'] for m in materials)))
print('pub dates', sum(1 for m in materials if m['pub_date']), 'radar only', sum(1 for m in materials if m['radar_dates']))

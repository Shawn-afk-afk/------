"""Project published AI Teaching Platform packs into student-visible material."""
import base64
import binascii
import json


MAX_BYTES = 5 * 1024 * 1024
RESOURCE_TYPES = {
    'handout': '講義', 'reading': '閱讀文章', 'comprehension': '理解題',
    'quiz': '測驗', 'vocabulary': '字彙活動', 'stations': '學習站',
    'exitTicket': '退出單', 'organizer': '圖像組織工具', 'tieredPractice': '分層練習',
}
QUESTION_TYPES = {
    'singleChoice': '單選', 'trueFalse': '是非', 'shortAnswer': '簡答',
    'multipleChoice': '多選', 'fillBlank': '填空', 'matching': '配對',
    'ordering': '排序', 'upload': '作品上傳',
}


def require(condition, message='教材包結構不完整或含有無效欄位'):
    if not condition:
        raise ValueError(message)


def field(record, key, expected):
    require(isinstance(record, dict) and type(record.get(key)) is expected)
    return record[key]


def line(record, key):
    value = field(record, key, str)
    require(value.strip() and '\x00' not in value)
    return value.strip()


def question_text(question, number):
    kind = line(question, 'type')
    require(kind in QUESTION_TYPES, '教材包包含不支援的題型')
    rows = [f'{number}. 【{QUESTION_TYPES[kind]}】{line(question, "prompt")}']
    if kind in ('singleChoice', 'multipleChoice'):
        options = field(question, 'options', list)
        require(len(options) >= 2)
        rows.extend(f'{i}. {line(option, "text")}' for i, option in enumerate(options, 1))
    elif kind == 'trueFalse':
        rows.append('選項：是／否')
    elif kind == 'fillBlank':
        rows.extend(f'{line(blank, "label")}：＿＿＿' for blank in field(question, 'blanks', list))
    elif kind == 'matching':
        rows.extend(f'{label}：' + '；'.join(line(item, 'text') for item in field(question, key, list))
                    for label, key in [('左欄', 'left'), ('右欄', 'right')])
    elif kind == 'ordering':
        rows.append('待排序項目：' + '；'.join(line(item, 'text')
                    for item in field(question, 'items', list)))
    return '\n'.join(rows)


def block_text(kind, data):
    if kind in ('heading', 'paragraph'):
        return line(data, 'text')
    if kind == 'vocabularyList':
        rows = []
        for entry in field(data, 'entries', list):
            example = field(entry, 'example', str).strip()
            definition = line(entry, 'definition')
            rows.append(f'{line(entry, "term")}：{definition}' + (f'\n例句：{example}' if example else ''))
        return '\n'.join(rows)
    require(kind == 'organizer', '教材包含不支援的內容區塊')
    nodes = {line(node, 'id'): line(node, 'label') for node in field(data, 'nodes', list)}
    rows = [line(data, 'title'), '概念：' + '；'.join(nodes.values())]
    for edge in field(data, 'edges', list):
        start, end = line(edge, 'from'), line(edge, 'to')
        require(start in nodes and end in nodes)
        relationship = field(edge, 'label', str).strip()
        rows.append(f'{nodes[start]} → {nodes[end]}' + (f'（{relationship}）' if relationship else ''))
    return '\n'.join(rows)


def read(encoded):
    limit = 4 * ((MAX_BYTES + 2) // 3)
    require(isinstance(encoded, str) and 0 < len(encoded) <= limit, '請選擇 5 MiB 以下的 JSON 教材包')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('檔案編碼不合法') from None
    require(len(raw) <= MAX_BYTES, '教材包上限為 5 MiB')
    try:
        pack = json.loads(raw.decode('utf-8-sig'))
    except (ValueError, RecursionError):
        raise ValueError('無法讀取 JSON 教材包') from None
    require(isinstance(pack, dict) and pack.get('format') == 'ai-teaching-resource-pack'
            and type(pack.get('packageVersion')) is int and pack['packageVersion'] == 1
            and pack.get('schemaVersion') in ('2.0.0', '3.0.0'), '不支援此教材包格式或版本')
    manifest = field(pack, 'manifest', dict)
    require(manifest.get('scope') == 'one-published-version'
            and manifest.get('sourceScope') == 'published-chunks-only'
            and manifest.get('attachments') == 'none' and manifest.get('studentData') is False
            and manifest.get('inputMode') in ('source', 'topic'), '只接受單一已發布版本且未含學生資料或附件的教材包')
    versions, resources = field(pack, 'versions', list), field(pack, 'resources', list)
    require(len(versions) == len(resources) == 1)
    version, resource = versions[0], resources[0]
    content = field(version, 'content', dict)
    version_id, resource_id = line(content, 'id'), line(resource, 'id')
    version_no = field(version, 'versionNo', int)
    kind = line(content, 'resourceType')
    require(version_no > 0 and kind in RESOURCE_TYPES
            and field(resource, 'latestPublishedVersionId', str) == version_id
            and 'currentDraftId' in resource and resource['currentDraftId'] is None
            and field(content, 'resourceId', str) == resource_id
            and resource.get('type') == kind, '教材包的發布版本與資源記錄不一致')
    title = line(content, 'title')
    require(len(title) <= 180, '教材名稱最多 180 字')

    questions = field(content, 'questions', list)
    question_map = {line(q, 'id'): q for q in questions}
    require(len(questions) == len(question_map), '教材包有重複的題目')
    sections, used = [], set()
    for block in field(content, 'blocks', list):
        visibility, block_type = line(block, 'visibility'), line(block, 'type')
        require(visibility in ('student', 'both', 'teacher'))
        if block_type == 'teacherNote' or visibility == 'teacher':
            continue
        data = field(block, 'data', dict)
        if block_type != 'questionSet':
            sections.append(block_text(block_type, data))
            continue
        for question_id in field(data, 'questionIds', list):
            require(isinstance(question_id, str) and question_id in question_map and question_id not in used,
                    '教材包的題組引用不一致')
            used.add(question_id)
            sections.append(question_text(question_map[question_id], len(used)))
    require(used == question_map.keys(), '教材包有未放入學生題組的題目')
    require(any(sections), '這份教材包沒有可匯入的學生版內容')
    label = RESOURCE_TYPES[kind]
    material = '\n\n'.join([title, f'{label} · v{version_no}', *sections])
    require(30 <= len(material) <= 250000, '轉換後的教材需為 30–250000 字')
    return {
        'title': title, 'type_label': label, 'version': version_no,
        'resource_id': resource_id, 'version_id': version_id,
        'question_count': len(used), 'text': material,
    }

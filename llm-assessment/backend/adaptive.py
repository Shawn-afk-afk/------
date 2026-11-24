"""Replay confirmed personal evidence. Versioned research estimates never drive grades."""
import math
from collections import defaultdict
from storage import decode, encode, uid

VERSION = 'personal-skills-v1'
# Demonstration priors, explicitly uncalibrated. RULE_ONLY is the decision policy.
PARAMETERS = {'initial': .2, 'learn': .1, 'guess': .2, 'slip': .1,
              'beta': -1., 'gamma': .5, 'rho': -.2}


def achieved(criterion):
    level = criterion.get('level')
    if level is None:
        return None
    return level >= (1 if criterion.get('max_level') == 1 else 2)


def bkt_update(prior, success):
    g, s = PARAMETERS['guess'], PARAMETERS['slip']
    predicted = prior * (1-s) + (1-prior) * g
    numerator = prior * ((1-s) if success else s)
    denominator = predicted if success else 1-predicted
    posterior = numerator / denominator
    return predicted, posterior + (1-posterior) * PARAMETERS['learn']


def profiles(c, learner_id):
    rows = c.execute('''SELECT p.report_json,p.id report_id,s.id submission_id,
        s.submitted_at, t.rowid attempt_order,
        t.id=(SELECT id FROM attempts WHERE submission_id=s.id ORDER BY rowid LIMIT 1) first_attempt
        FROM published_reports p JOIN submissions s ON s.id=p.submission_id
        JOIN attempts t ON t.id=json_extract(p.report_json,'$.attempt_id') AND t.submission_id=s.id
        WHERE s.learner_id=? AND p.rowid=(SELECT MAX(p2.rowid) FROM published_reports p2
        WHERE p2.submission_id=p.submission_id
        AND json_extract(p2.report_json,'$.attempt_id')=t.id)
        ORDER BY COALESCE((SELECT MIN(j.created_at) FROM analysis_jobs j WHERE j.attempt_id=t.id), t.rowid),t.rowid,s.id''', (learner_id,)).fetchall()
    skills = {}
    seen = set()
    for row in rows:
        report = decode(row['report_json'])
        for item in report.get('items', []):
            grouped = defaultdict(list)
            for criterion in item.get('criteria', []):
                grouped[criterion.get('skill_id') or item.get('skill_id')].append(criterion)
            for skill, criteria in grouped.items():
                if not skill:
                    continue
                state = skills.setdefault(skill, {
                    'skill_id': skill, 'state': '證據不足', 'successes': 0, 'failures': 0,
                    'mastery_probability': PARAMETERS['initial'], 'correctness_probability': 1/(1+math.exp(1)),
                    'evidence': [], 'policy': 'RULE_ONLY', 'model_version': VERSION,
                    'calibrated': False, 'success_streak': 0, 'failure_streak': 0})
                key = (skill, item.get('question_id') or item['question_version_id'])
                condition = report.get('evidence_condition', 'unknown')
                reason = ''
                values = [achieved(x) for x in criteria]
                if None in values or not item.get('complete'):
                    reason = '評分尚未完整'
                elif item.get('kind') == 'ai_collab_canvas':
                    reason = '協作證據需另行個人驗證'
                elif not row['first_attempt'] or key in seen:
                    reason = '同題重答，保留紀錄'
                elif condition != 'independent':
                    reason = '有提示作答' if condition == 'supported' else '獨立作答條件尚未確認'
                elif not any(x.get('quote') for x in criteria):
                    reason = '缺少可定位的個人作答證據'
                seen.add(key)
                evidence = {'question_id': key[1], 'title': item.get('title'),
                            'report_id': row['report_id'], 'submission_id': row['submission_id'],
                            'success': all(values) if None not in values else None,
                            'excluded_reason': reason}
                state['evidence'].append(evidence)
                if reason:
                    if condition == 'supported' and values and all(values) and state['state'] != '本輪獨立驗證通過':
                        state['state'] = '待驗證'
                    continue
                success = all(values)
                evidence['bkt_prediction_before'], state['mastery_probability'] = bkt_update(state['mastery_probability'], success)
                evidence['pfa_prediction_before'] = state['correctness_probability']
                state['successes'] += int(success)
                state['failures'] += int(not success)
                state['success_streak'] = state['success_streak'] + 1 if success else 0
                state['failure_streak'] = state['failure_streak'] + 1 if not success else 0
                z = PARAMETERS['beta'] + PARAMETERS['gamma']*state['successes'] + PARAMETERS['rho']*state['failures']
                state['correctness_probability'] = 1/(1+math.exp(-max(-700, min(700,z))))
                if state['success_streak'] >= 2:
                    state['state'] = '本輪獨立驗證通過'
                elif success:
                    state['state'] = '待驗證'
                elif state['failure_streak'] >= 2:
                    state['state'] = '待補強'
                else:
                    state['state'] = '待確認'
    return list(skills.values())


def refresh_recommendations(c, learner_id):
    # Called in the publication transaction. Replace owned drafts, keep other decisions.
    c.execute("DELETE FROM recommendations WHERE learner_id=? AND review_status='draft' AND json_extract(reason_json,'$.algorithm') IN (?, 'skill-filter-v1')", (learner_id, VERSION))
    used = {r[0] for r in c.execute('''SELECT v.question_id FROM assignment_items ai
        JOIN assignment_recipients ar ON ar.assignment_id=ai.assignment_id
        JOIN question_versions v ON v.id=ai.question_version_id WHERE ar.learner_id=?''', (learner_id,))}
    used.update(r[0] for r in c.execute('''SELECT v.question_id FROM recommendations r
        JOIN question_versions v ON v.id=r.question_version_id WHERE r.learner_id=?''', (learner_id,)))
    pool = c.execute('''SELECT v.id,v.question_id,q.skill_id,v.rubric_json FROM question_versions v
        JOIN questions q ON q.id=v.question_id WHERE v.review_status='approved'
        AND v.version=(SELECT MAX(v2.version) FROM question_versions v2 WHERE v2.question_id=v.question_id)
        ORDER BY v.question_id''').fetchall()
    purposes = {'證據不足': '確認', '待確認': '確認', '待補強': '補強', '待驗證': '無提示驗證'}
    for state in profiles(c, learner_id):
        purpose = purposes.get(state['state'])
        if not purpose:
            continue
        candidates = [q for q in pool if state['skill_id'] in {r.get('skill_id') or q['skill_id'] for r in decode(q['rubric_json']).get('criteria', [])} and q['question_id'] not in used]
        for item in candidates[:1]:
            reason = {'algorithm': VERSION, 'skill': state['skill_id'], 'purpose': purpose,
                      'reason': f"{state['skill_id']}目前為{state['state']}，建議安排{purpose}題；請確認情境與規準適切性。",
                      'policy': 'RULE_ONLY', 'evidence_report_ids': sorted({e['report_id'] for e in state['evidence']})}
            c.execute('INSERT INTO recommendations VALUES(?,?,?,?,?)', (uid(), learner_id, item['id'], encode(reason), 'draft'))
            used.add(item['question_id'])

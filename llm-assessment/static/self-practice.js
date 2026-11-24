'use strict';

async function selfPractice() {
    const data = await api('/api/self-practice');
    content(head('', '自主練習', '用教師開放的教材產生自己的練習題。') + `
        <section class="panel">
            <h2>選擇教材</h2>
            ${data.materials.length ? `
                <form id="self-practice-form">
                    ${field('practice-material', '教材', `<select id="practice-material">${data.materials.map(material =>
                        `<option value="${esc(material.id)}">${esc(studioSubjects[material.subject] || material.subject)} · ${esc(material.title)}</option>`
                    ).join('')}</select>`)}
                    ${field('practice-topic', '想練習的主題（選填）', input('practice-topic', 'text', '', 'maxlength="180"'))}
                    ${field('practice-count', '題數', '<select id="practice-count"><option value="3">3 題</option><option value="5">5 題</option></select>')}
                    <button class="btn primary" id="practice-generate">生成單選題</button>
                    <p id="practice-status" role="status"></p>
                </form>
            ` : '<p>目前沒有已開放的教材。教師可從教材出題工作室開放自主練習。</p>'}
        </section>
        <section class="panel">
            <h2>練習紀錄</h2>
            ${data.history.map(quiz => `<div class="list-row">
                <div><strong>${esc(quiz.title)}</strong>
                <p>${quiz.topic ? esc(quiz.topic) + ' · ' : ''}${fmt(quiz.created_at * 1000)}</p></div>
                <button class="btn" data-practice-quiz="${esc(quiz.id)}">${quiz.completed ? '查看結果' : '繼續作答'}</button>
            </div>`).join('') || '<p>尚無練習紀錄。</p>'}
        </section>`);
    const form = $('#self-practice-form');
    if (form) {
        form.onsubmit = busy($('#practice-generate'), async () => {
            const status = $('#practice-status');
            const navigation = state.navigation;
            status.textContent = '正在根據教材生成題目…';
            try {
                const quiz = await api('/api/self-practice', {
                    material_id: $('#practice-material').value,
                    topic: $('#practice-topic').value.trim(),
                    count: Number($('#practice-count').value),
                });
                if (navigation === state.navigation) await openSelfPractice(quiz.id);
            } finally {
                status.textContent = '';
            }
        });
    }
    for (const button of $$('[data-practice-quiz]')) {
        button.onclick = busy(button, () => openSelfPractice(button.dataset.practiceQuiz));
    }
}

async function openSelfPractice(id) {
    renderSelfPractice(await api('/api/self-practice/' + encodeURIComponent(id)));
}

function renderSelfPractice(quiz) {
    const completed = Array.isArray(quiz.answers);
    const items = quiz.questions.map((question, index) => {
        const options = question.options.map((option, choice) => {
            const id = `practice-${index}-${choice}`;
            return `<div class="field-row"><input type="radio" id="${id}" name="question-${index}" value="${choice}"
                ${completed ? (quiz.answers[index] === choice ? 'checked disabled' : 'disabled') : 'required'}>
                <label for="${id}">${esc(option)}</label></div>`;
        }).join('');
        const feedback = completed ? `<p><strong>${quiz.answers[index] === question.correct ? '答對' : '答錯'}</strong>
            · 正確答案：${esc(question.options[question.correct])}</p>
            <p>${esc(question.explanation)}</p>
            <details><summary>教材出處</summary><p>${esc(question.locator)}</p><blockquote>${esc(question.quote)}</blockquote></details>` : '';
        return `<fieldset class="panel practice-question"><legend>第 ${index + 1} 題</legend><p>${esc(question.stem)}</p>${options}${feedback}</fieldset>`;
    }).join('');
    content(head('', quiz.title, quiz.topic ? '主題 · ' + quiz.topic : '教材自主練習',
        '<button class="btn" id="back-self-practice">返回自主練習</button>') +
        (completed ? `<section class="panel"><h2>答對 ${quiz.score}／${quiz.questions.length} 題</h2></section>` + items
            : `<form id="practice-answers">${items}<button class="btn primary" id="practice-submit">交卷並看解析</button></form>`));
    bind('#back-self-practice', 'click', () => navigate('selfpractice'));
    if (!completed) {
        $('#practice-answers').onsubmit = busy($('#practice-submit'), async event => {
            const values = new FormData(event.target);
            const answers = quiz.questions.map((_, index) => Number(values.get('question-' + index)));
            const navigation = state.navigation;
            const result = await api('/api/self-practice/' + encodeURIComponent(quiz.id), {answers});
            if (navigation === state.navigation) renderSelfPractice(result);
        });
    }
}

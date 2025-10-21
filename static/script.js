document.addEventListener('DOMContentLoaded', () => {
    const single = {
        area: document.getElementById('singleUploadArea'),
        input: document.getElementById('singleFileInput'),
        preview: document.getElementById('singleFilePreview'),
        list: document.getElementById('singleFileList'),
        processBtn: document.getElementById('processSingle'),
        files: []
    };

    const batch = {
        area: document.getElementById('batchUploadArea'),
        input: document.getElementById('batchFileInput'),
        preview: document.getElementById('batchFilePreview'),
        list: document.getElementById('batchFileList'),
        processBtn: document.getElementById('processBatch'),
        files: []
    };

    const opts = {
        pad: document.getElementById('pad'),
        overlay: document.getElementById('overlay'),
        enforceInitials: document.getElementById('enforce_initials')
    };

    const resultsSection = document.getElementById('resultsSection');
    const resultsContent = document.getElementById('resultsContent');
    const downloadBtn = document.getElementById('downloadResults');
    const loadingModalEl = document.getElementById('loadingModal');
    const loadingModal = loadingModalEl ? new bootstrap.Modal(loadingModalEl, { backdrop: 'static', keyboard: false }) : null;

    let currentSessionId = null;

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    function highlight(el) {
        el.classList.add('dragover');
    }

    function unhighlight(el) {
        el.classList.remove('dragover');
    }

    function isImage(file) {
        return /^image\//.test(file.type);
    }

    function formatBytes(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    function renderList(target, files) {
        target.innerHTML = '';
        files.forEach((f) => {
            const item = document.createElement('div');
            item.className = 'file-item';
            item.innerHTML = `
                <div class="file-info">
                    <i class="fas fa-file-image file-icon"></i>
                    <div class="file-details">
                        <p class="file-name">${f.name}</p>
                        <p class="file-size">${formatBytes(f.size)}</p>
                    </div>
                </div>
                <div class="file-status">
                    <span class="status-badge status-ready">Ready</span>
                </div>
            `;
            target.appendChild(item);
        });
    }

    function handleAreaDragAndDrop(scope) {
        if (!scope.area) return;
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            scope.area.addEventListener(eventName, preventDefaults, false);
        });
        ['dragenter', 'dragover'].forEach(eventName => {
            scope.area.addEventListener(eventName, () => highlight(scope.area), false);
        });
        ['dragleave', 'drop'].forEach(eventName => {
            scope.area.addEventListener(eventName, () => unhighlight(scope.area), false);
        });
        scope.area.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            const files = Array.from(dt.files).filter(isImage);
            if (scope === single) {
                scope.files = files.slice(0, 2); // single pair expects 2 images
            } else {
                scope.files = files;
            }
            if (scope.files.length > 0) {
                scope.preview.style.display = '';
                renderList(scope.list, scope.files);
            }
        });
    }

    function handleAreaBrowse(scope) {
        if (!scope.input || !scope.area) return;
        // Let clicking the area open file dialog, in addition to the button
        scope.area.addEventListener('click', () => scope.input.click());
        scope.input.addEventListener('change', () => {
            const files = Array.from(scope.input.files).filter(isImage);
            if (scope === single) {
                scope.files = files.slice(0, 2);
            } else {
                scope.files = files;
            }
            if (scope.files.length > 0) {
                scope.preview.style.display = '';
                renderList(scope.list, scope.files);
            }
        });
    }

    async function postFiles(url, files) {
        const form = new FormData();
        files.forEach(f => form.append('files', f));
        const padVal = parseFloat(opts.pad && opts.pad.value || '0.02');
        form.append('pad', isFinite(padVal) ? String(padVal) : '0.02');
        form.append('overlay', opts.overlay && opts.overlay.checked ? 'true' : 'false');
        form.append('enforce_initials', opts.enforceInitials && opts.enforceInitials.checked ? 'true' : 'false');
        const res = await fetch(url, { method: 'POST', body: form });
        if (!res.ok) {
            const text = await res.text().catch(() => '');
            throw new Error(text || `HTTP ${res.status}`);
        }
        return res.json();
    }

    function showLoading(show) {
        if (!loadingModal) return;
        if (show) loadingModal.show(); else loadingModal.hide();
    }

    function renderResults(json) {
        resultsSection.style.display = '';
        const out = json.result || json; // API wraps under { success, session_id, result }

        // Batch mode: out has { count, items: [...] }
        if (out && Array.isArray(out.items) && out.items.length > 0) {
            const cards = out.items.map((it, idx) => {
                const r = it.result || {};
                const variant = (r.variant && r.variant.detected) || '';
                const nationality = (r.outputs && r.outputs.nationality) || {};
                const rb = (r.outputs && r.outputs.right_band && (r.outputs.right_band.normalized || r.outputs.right_band)) || {};
                const fio = (r.outputs && r.outputs.fio) || {};
                const natStr = typeof nationality === 'object' ? JSON.stringify(nationality, null, 2) : String(nationality);
                const fioStr = typeof fio === 'object' ? JSON.stringify({ surname: fio.surname, name: fio.name, patronymic: fio.patronymic, confidence: fio.confidence }, null, 2) : String(fio);
                const rbStr = typeof rb === 'object' ? JSON.stringify(rb, null, 2) : String(rb);

                const pair = Array.isArray(it.pair) ? it.pair.map(p => `<code>${p}</code>`).join(' , ') : '';

                return `
                <div class="result-card">
                    <div class="result-header">
                        <h6 class="result-title">Pair ${idx + 1} ${variant ? `· Variant: ${variant}` : ''}</h6>
                    </div>
                    <div class="result-content">
                        <div class="result-field"><span class="result-label">Inputs:</span><span class="result-value">${pair}</span></div>
                    </div>
                    <div class="result-content">
                        <h6 class="result-title">Nationality</h6>
                        <pre style="white-space:pre-wrap;">${natStr}</pre>
                    </div>
                    <div class="result-content">
                        <h6 class="result-title">Right band (surname + initials)</h6>
                        <pre style="white-space:pre-wrap;">${rbStr}</pre>
                    </div>
                    <div class="result-content">
                        <h6 class="result-title">FIO (final)</h6>
                        <pre style="white-space:pre-wrap;">${fioStr}</pre>
                    </div>
                </div>`;
            }).join('');

            resultsContent.innerHTML = `
                <div class="result-card" style="margin-bottom:1rem;">
                    <div class="result-header"><h6 class="result-title">Batch Summary</h6></div>
                    <div class="result-content">
                        <div class="result-field"><span class="result-label">Pairs processed:</span><span class="result-value">${out.count}</span></div>
                    </div>
                </div>
                <div class="results-grid">${cards}</div>
            `;
            return;
        }

        // Single mode
        const nationality = (out.outputs && out.outputs.nationality) || {};
        const rightBand = (out.outputs && out.outputs.right_band) || {};
        const fio = (out.outputs && out.outputs.fio) || {};
        const natStr = typeof nationality === 'object' ? JSON.stringify(nationality, null, 2) : String(nationality);
        const fioStr = typeof fio === 'object' ? JSON.stringify({ surname: fio.surname, name: fio.name, patronymic: fio.patronymic, confidence: fio.confidence }, null, 2) : String(fio);
        const rbStr = typeof rightBand === 'object' ? JSON.stringify(rightBand.normalized || rightBand, null, 2) : String(rightBand);

        resultsContent.innerHTML = `
            <div class="results-grid">
                <div class="result-card">
                    <div class="result-header">
                        <h6 class="result-title">Nationality</h6>
                    </div>
                    <pre style="white-space:pre-wrap;">${natStr}</pre>
                </div>
                <div class="result-card">
                    <div class="result-header">
                        <h6 class="result-title">Right band (surname + initials)</h6>
                    </div>
                    <pre style="white-space:pre-wrap;">${rbStr}</pre>
                </div>
                <div class="result-card">
                    <div class="result-header">
                        <h6 class="result-title">FIO (final)</h6>
                    </div>
                    <pre style="white-space:pre-wrap;">${fioStr}</pre>
                </div>
            </div>
        `;
    }

    async function handleProcess(scope) {
        if (!scope.files || scope.files.length === 0) return;
        try {
            showLoading(true);
            const isSingle = (scope === single);
            const url = isSingle ? '/upload' : '/batch';
            const data = await postFiles(url, scope.files);
            currentSessionId = data.session_id || null;
            renderResults(data);
        } catch (err) {
            resultsSection.style.display = '';
            resultsContent.innerHTML = `
                <div class="error-message">${(err && err.message) ? err.message : 'Upload failed'}</div>
            `;
        } finally {
            showLoading(false);
        }
    }

    if (single.processBtn) single.processBtn.addEventListener('click', () => handleProcess(single));
    if (batch.processBtn) batch.processBtn.addEventListener('click', () => handleProcess(batch));

    handleAreaDragAndDrop(single);
    handleAreaDragAndDrop(batch);
    handleAreaBrowse(single);
    handleAreaBrowse(batch);

    if (downloadBtn) {
        downloadBtn.addEventListener('click', async () => {
            if (!currentSessionId) return;
            try {
                const res = await fetch(`/results/${currentSessionId}`);
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const blob = await res.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `results_${currentSessionId}.json`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                URL.revokeObjectURL(url);
            } catch (e) {
                // noop; could show an error toast
            }
        });
    }
});



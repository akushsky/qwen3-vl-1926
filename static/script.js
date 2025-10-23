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
    const viewJsonBtn = document.getElementById('viewJson');
    const progressEls = {
        container: document.getElementById('progressContainer'),
        bar: document.getElementById('progressBar'),
        label: document.getElementById('progressLabel'),
        percent: document.getElementById('progressPercent')
    };
    const loadingModalEl = document.getElementById('loadingModal');
    const loadingModal = loadingModalEl ? new bootstrap.Modal(loadingModalEl, { backdrop: 'static', keyboard: false }) : null;
    const imageModalEl = document.getElementById('imageModal');
    const imageModal = imageModalEl ? new bootstrap.Modal(imageModalEl) : null;
    const imageModalImg = document.getElementById('imageModalImg');
    const jsonModalEl = document.getElementById('jsonModal');
    const jsonModal = jsonModalEl ? new bootstrap.Modal(jsonModalEl) : null;
    const jsonModalCode = document.getElementById('jsonModalCode');

    let currentSessionId = null;
    let pollTimer = null;
    let lastResultJson = null;

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
                const fio = (r.outputs && r.outputs.fio) || {};
                const page1Name = (r.inputs && r.inputs.page1) || '';
                const fioValue = [fio.surname || '', fio.name || '', fio.patronymic || ''].filter(Boolean).join(' ');
                return `
                <div class="result-card">
                    <div class="result-header">
                        <h6 class="result-title">Pair ${idx + 1} ${variant ? `· Variant: ${variant}` : ''}</h6>
                    </div>
                    <div class="result-content">
                        <div class="mb-3 form-check">
                            <input type="checkbox" class="form-check-input" id="editIsJewish_${idx}" ${((nationality || {}).is_jewish ? 'checked' : '')}>
                            <label class="form-check-label" for="editIsJewish_${idx}">is_jewish</label>
                        </div>
                        <div class="mb-3">
                            <label class="form-label" for="editFullFio_${idx}">Full FIO</label>
                            <input type="text" class="form-control" id="editFullFio_${idx}" value="${fioValue}">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Page 1</label>
                            <div>
                                <img data-idx="${idx}" class="page1-thumb" src="/crops/${currentSessionId}/${encodeURIComponent(page1Name)}" alt="Page 1" style="max-width: 220px; height: auto; border: 1px solid #dee2e6; border-radius: 6px; cursor: pointer;" />
                            </div>
                            <small class="text-muted">Click to open full size</small>
                        </div>
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

            // Wire up thumbnails
            const thumbs = resultsContent.querySelectorAll('img.page1-thumb');
            if (thumbs && imageModal && imageModalImg) {
                thumbs.forEach(img => {
                    img.addEventListener('click', () => {
                        imageModalImg.src = img.src;
                        imageModal.show();
                    });
                });
            }
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
                    <div class="result-header"><h6 class="result-title">Edit Result</h6></div>
                    <div class="result-content">
                        <div class="mb-3 form-check">
                            <input type="checkbox" class="form-check-input" id="editIsJewish" ${((nationality || {}).is_jewish ? 'checked' : '')}>
                            <label class="form-check-label" for="editIsJewish">is_jewish</label>
                        </div>
                        <div class="mb-3">
                            <label class="form-label" for="editFullFio">Full FIO</label>
                            <input type="text" class="form-control" id="editFullFio" value="${[fio.surname || '', fio.name || '', fio.patronymic || ''].filter(Boolean).join(' ')}">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">Page 1</label>
                            <div>
                                <img id="page1Thumb" src="/crops/${currentSessionId}/${encodeURIComponent((out.inputs && out.inputs.page1) || '')}" alt="Page 1" style="max-width: 220px; height: auto; border: 1px solid #dee2e6; border-radius: 6px; cursor: pointer;" />
                            </div>
                            <small class="text-muted">Click to open full size</small>
                        </div>
                    </div>
                </div>
            </div>
        `;

        const thumb = document.getElementById('page1Thumb');
        if (thumb && imageModal && imageModalImg) {
            thumb.addEventListener('click', () => {
                imageModalImg.src = thumb.src;
                imageModal.show();
            });
        }
    }

    function updateProgressUI(percent, stage) {
        if (!progressEls.container) return;
        progressEls.container.style.display = '';
        const p = Math.max(0, Math.min(100, Number(percent) || 0));
        if (progressEls.bar) progressEls.bar.style.width = `${p}%`;
        if (progressEls.percent) progressEls.percent.textContent = `${p}%`;
        if (progressEls.label) {
            const map = {
                queued: 'Queued',
                started: 'Starting…',
                variant_detected: 'Detected form variant',
                crops_saved: 'Prepared crops',
                nationality_done: 'Analyzed nationality',
                right_band_done: 'Extracted surname and initials',
                fio_done: 'Read full FIO',
                assembled_output: 'Finalizing results',
                completed: 'Completed'
            };
            progressEls.label.textContent = map[stage] || (stage || 'Processing…');
        }
    }

    async function fetchAndRenderResults() {
        if (!currentSessionId) return;
        const res = await fetch(`/results/${currentSessionId}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        lastResultJson = json;
        if (progressEls.container) progressEls.container.style.display = 'none';
        renderResults(json);
    }

    function startPolling(sessionId) {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
        updateProgressUI(0, 'queued');
        const poll = async () => {
            try {
                const r = await fetch(`/progress/${sessionId}`);
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                const j = await r.json();
                updateProgressUI(j.progress || 0, j.stage || j.status);
                if (j.status === 'done') {
                    clearInterval(pollTimer);
                    pollTimer = null;
                    await fetchAndRenderResults();
                } else if (j.status === 'error') {
                    clearInterval(pollTimer);
                    pollTimer = null;
                    resultsSection.style.display = '';
                    resultsContent.innerHTML = `<div class="error-message">${j.error || 'Processing failed'}</div>`;
                }
            } catch (e) {
                // transient error; keep polling
            }
        };
        poll();
        pollTimer = setInterval(poll, 1200);
    }

    async function handleProcess(scope) {
        if (!scope.files || scope.files.length === 0) return;
        try {
            const isSingle = (scope === single);
            const url = isSingle ? '/upload' : '/batch';
            const data = await postFiles(url, scope.files);
            currentSessionId = data.session_id || null;
            resultsSection.style.display = '';
            resultsContent.innerHTML = '';
            if (currentSessionId) {
                if (progressEls.container) progressEls.container.style.display = '';
                startPolling(currentSessionId);
            } else {
                // Batch mode: render immediately (server returns full results)
                renderResults(data);
            }
        } catch (err) {
            resultsSection.style.display = '';
            resultsContent.innerHTML = `
                <div class="error-message">${(err && err.message) ? err.message : 'Upload failed'}</div>
            `;
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

    if (viewJsonBtn && jsonModal && jsonModalCode) {
        viewJsonBtn.addEventListener('click', async () => {
            try {
                if (!lastResultJson && currentSessionId) {
                    const r = await fetch(`/results/${currentSessionId}`);
                    if (!r.ok) throw new Error(`HTTP ${r.status}`);
                    lastResultJson = await r.json();
                }
                const text = JSON.stringify(lastResultJson || {}, null, 2);
                jsonModalCode.textContent = text;
                if (window.hljs) {
                    try { window.hljs.highlightElement(jsonModalCode); } catch (_) {}
                }
                jsonModal.show();
            } catch (e) {
                // ignore
            }
        });
    }
});



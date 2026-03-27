/**
 * Transactions page — keyboard shortcuts & inline editing
 *
 * Shortcuts:
 *   e        → inline-edit hovered row (description, merchant, amount, currency)
 *   0        → clear category on hovered row
 *   1-9/a-z  → assign category (configured in shortcut modal)
 *   Escape   → cancel / close edit row
 *   Enter    → save inline edit
 */

(function () {
    'use strict';

    const STORAGE_KEY = 'tx_shortcuts';   // {key: category_id}

    /* ── State ─────────────────────────────────────────────────── */
    let hoveredRow = null;      // <tr data-tx-id="…">
    let editingTxId = null;     // id of the row currently open in inline-edit

    /* ── Category cache ─────────────────────────────────────────── */
    let categories = [];        // [{id, name, icon, color}]

    async function loadCategories() {
        try {
            const r = await fetch('/api/categories');
            categories = await r.json();
        } catch (e) {
            console.error('Failed to load categories', e);
        }
    }

    /* ── Shortcuts storage ──────────────────────────────────────── */
    function getShortcuts() {
        try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); }
        catch { return {}; }
    }

    function saveShortcuts(obj) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(obj));
    }

    /* ── Hover tracking ─────────────────────────────────────────── */
    function attachHoverTracking() {
        document.querySelectorAll('tbody tr[data-tx-id]').forEach(function (tr) {
            tr.addEventListener('mouseenter', function () { hoveredRow = tr; });
            tr.addEventListener('mouseleave', function () {
                // keep hoveredRow while cursor is in the edit row below
                const next = tr.nextElementSibling;
                if (!next || !next.classList.contains('inline-edit-row')) {
                    hoveredRow = tr;   // still set — cleared only when entering another row
                }
            });
        });
    }

    /* ── Inline edit ─────────────────────────────────────────────── */
    function openEditRow(tr) {
        if (!tr) return;
        const id = tr.dataset.txId;
        if (editingTxId === id) return;   // already open

        closeEditRow();   // close any previously open row

        const editTr = document.getElementById('edit-row-' + id);
        if (!editTr) return;

        // Populate inputs from data attributes
        editTr.querySelector('[name=description_clean]').value = tr.dataset.txDescription || '';
        editTr.querySelector('[name=merchant]').value = tr.dataset.txMerchant || '';
        editTr.querySelector('[name=amount]').value = tr.dataset.txAmount || '';
        editTr.querySelector('[name=currency]').value = tr.dataset.txCurrency || '';

        editTr.style.display = '';
        editTr.querySelector('[name=description_clean]').focus();
        editingTxId = id;
        tr.classList.add('editing');
    }

    function closeEditRow() {
        if (!editingTxId) return;
        const editTr = document.getElementById('edit-row-' + editingTxId);
        if (editTr) editTr.style.display = 'none';
        const mainTr = document.querySelector('tr[data-tx-id="' + editingTxId + '"]');
        if (mainTr) mainTr.classList.remove('editing');
        editingTxId = null;
    }

    async function saveEditRow(txId) {
        const editTr = document.getElementById('edit-row-' + txId);
        if (!editTr) return;

        const payload = {
            description_clean: editTr.querySelector('[name=description_clean]').value.trim(),
            merchant: editTr.querySelector('[name=merchant]').value.trim(),
            amount: parseFloat(editTr.querySelector('[name=amount]').value),
            currency: editTr.querySelector('[name=currency]').value.trim().toUpperCase(),
        };

        try {
            const r = await fetch('/api/transactions/' + txId, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (!r.ok) throw new Error('HTTP ' + r.status);
            const updated = await r.json();

            // Update the main row's displayed values + data attributes
            const mainTr = document.querySelector('tr[data-tx-id="' + txId + '"]');
            if (mainTr) {
                mainTr.dataset.txDescription = updated.description_clean || updated.description || '';
                mainTr.dataset.txMerchant = updated.merchant || '';
                mainTr.dataset.txAmount = updated.amount;
                mainTr.dataset.txCurrency = updated.currency;

                const descCell = mainTr.querySelector('.tx-description');
                if (descCell) descCell.textContent = updated.description_clean || updated.description || '';

                const merchantCell = mainTr.querySelector('.tx-merchant');
                if (merchantCell) merchantCell.textContent = updated.merchant || '—';

                const amtCell = mainTr.querySelector('.tx-amount');
                if (amtCell) {
                    amtCell.textContent = updated.amount.toFixed(2);
                    amtCell.className = 'tx-amount ' + (updated.amount >= 0 ? 'amount-positive' : 'amount-negative');
                }

                const currCell = mainTr.querySelector('.tx-currency');
                if (currCell) currCell.textContent = updated.currency;
            }

            closeEditRow();
            showToast('Transaction updated', 'success');
        } catch (e) {
            showToast('Save failed: ' + e.message, 'error');
        }
    }

    /* ── Category assignment ─────────────────────────────────────── */
    async function assignCategory(tr, categoryId) {
        if (!tr) return;
        const txId = tr.dataset.txId;

        try {
            const r = await fetch('/api/transactions/' + txId, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ category_id: categoryId }),
            });
            if (!r.ok) throw new Error('HTTP ' + r.status);
            const updated = await r.json();

            // Update badge in the row
            const catCell = tr.querySelector('.tx-category');
            if (catCell) {
                if (updated.category_name) {
                    catCell.innerHTML = '<span class="badge badge-category" style="--cat-color:' +
                        (updated.category_color || '#9E9E9E') + '">' +
                        (updated.category_icon ? updated.category_icon + ' ' : '') +
                        updated.category_name + '</span>';
                } else {
                    catCell.innerHTML = '<span class="text-muted text-sm">—</span>';
                }
            }

            const label = categoryId === null
                ? 'Category cleared'
                : 'Category: ' + (updated.category_name || 'set');
            showToast(label, 'success');
        } catch (e) {
            showToast('Failed: ' + e.message, 'error');
        }
    }

    /* ── Keyboard handler ───────────────────────────────────────── */
    document.addEventListener('keydown', function (e) {
        // Ignore when user is typing in an input / textarea / select
        const tag = e.target.tagName;
        const isInput = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';

        if (e.key === 'Escape') {
            closeEditRow();
            return;
        }

        // Allow Enter inside the edit row to save
        if (e.key === 'Enter' && isInput && editingTxId) {
            // Only if the focused element is inside an edit row
            const editTr = document.getElementById('edit-row-' + editingTxId);
            if (editTr && editTr.contains(e.target)) {
                e.preventDefault();
                saveEditRow(editingTxId);
                return;
            }
        }

        // All other shortcuts only fire when not focused in an input
        if (isInput) return;

        if (e.key === 'e' || e.key === 'E') {
            if (hoveredRow) {
                e.preventDefault();
                openEditRow(hoveredRow);
            }
            return;
        }

        if (e.key === '0') {
            if (hoveredRow) {
                e.preventDefault();
                assignCategory(hoveredRow, null);
            }
            return;
        }

        // Digit / letter shortcuts for category assignment
        const shortcuts = getShortcuts();
        const categoryId = shortcuts[e.key];
        if (categoryId !== undefined && hoveredRow) {
            e.preventDefault();
            assignCategory(hoveredRow, parseInt(categoryId, 10));
        }
    });

    /* ── Attach save/cancel buttons inside edit rows ─────────────── */
    function attachEditRowButtons() {
        document.querySelectorAll('.inline-edit-row').forEach(function (editTr) {
            const txId = editTr.dataset.editTxId;

            const saveBtn = editTr.querySelector('.edit-save-btn');
            if (saveBtn) saveBtn.addEventListener('click', function () { saveEditRow(txId); });

            const cancelBtn = editTr.querySelector('.edit-cancel-btn');
            if (cancelBtn) cancelBtn.addEventListener('click', function () { closeEditRow(); });
        });
    }

    /* ── Shortcut config modal ───────────────────────────────────── */
    function buildShortcutModal() {
        const container = document.getElementById('shortcut-modal-body');
        if (!container) return;

        const shortcuts = getShortcuts();
        container.innerHTML = '';

        // Category → key mapping table
        const table = document.createElement('table');
        table.style.width = '100%';
        table.style.borderCollapse = 'collapse';
        table.innerHTML = '<thead><tr>' +
            '<th style="text-align:left;padding:6px 8px;border-bottom:1px solid var(--border-color)">Category</th>' +
            '<th style="text-align:left;padding:6px 8px;border-bottom:1px solid var(--border-color)">Shortcut key</th>' +
            '</tr></thead>';

        const tbody = document.createElement('tbody');
        categories.forEach(function (cat) {
            const assignedKey = Object.entries(shortcuts).find(([k, v]) => String(v) === String(cat.id));
            const currentKey = assignedKey ? assignedKey[0] : '';

            const tr = document.createElement('tr');
            tr.innerHTML =
                '<td style="padding:6px 8px">' +
                '<span class="badge badge-category" style="--cat-color:' + (cat.color || '#9E9E9E') + '">' +
                (cat.icon ? cat.icon + ' ' : '') + cat.name + '</span></td>' +
                '<td style="padding:6px 8px">' +
                '<input type="text" maxlength="1" value="' + currentKey + '" ' +
                'data-cat-id="' + cat.id + '" ' +
                'style="width:50px;text-align:center;font-size:16px;padding:4px" ' +
                'class="form-control shortcut-key-input" placeholder="—">' +
                '</td>';
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        container.appendChild(table);

        // Note about reserved keys
        const note = document.createElement('p');
        note.className = 'text-muted text-sm';
        note.style.marginTop = '12px';
        note.textContent = 'Reserved: e = edit, 0 = clear category. Avoid using these.';
        container.appendChild(note);
    }

    function saveShortcutModal() {
        const newShortcuts = {};
        document.querySelectorAll('.shortcut-key-input').forEach(function (input) {
            const key = input.value.trim();
            const catId = input.dataset.catId;
            if (key && key !== 'e' && key !== '0') {
                newShortcuts[key] = catId;
            }
        });
        saveShortcuts(newShortcuts);
        closeModal('shortcut-modal');
        showToast('Shortcuts saved', 'success');

        // Update the hint bar
        renderShortcutHints();
    }

    function renderShortcutHints() {
        const bar = document.getElementById('shortcut-hints');
        if (!bar) return;

        const shortcuts = getShortcuts();
        const parts = ['<span class="text-muted text-sm"><strong>e</strong>=edit &nbsp; <strong>0</strong>=clear'];
        Object.entries(shortcuts).forEach(function ([key, catId]) {
            const cat = categories.find(c => String(c.id) === String(catId));
            if (cat) {
                parts.push('<strong>' + key + '</strong>=' + (cat.icon ? cat.icon + ' ' : '') + cat.name);
            }
        });
        parts.push('</span>');
        bar.innerHTML = parts.join(' &nbsp; ');
    }

    /* ── Init ──────────────────────────────────────────────────── */
    document.addEventListener('DOMContentLoaded', async function () {
        await loadCategories();
        attachHoverTracking();
        attachEditRowButtons();
        renderShortcutHints();

        // Wire up shortcut modal open/save buttons
        const openBtn = document.getElementById('open-shortcut-modal-btn');
        if (openBtn) openBtn.addEventListener('click', function () {
            buildShortcutModal();
            openModal('shortcut-modal');
        });

        const saveBtn = document.getElementById('save-shortcuts-btn');
        if (saveBtn) saveBtn.addEventListener('click', saveShortcutModal);
    });

})();

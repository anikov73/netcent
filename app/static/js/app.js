// Theme toggle
(function () {
    const stored = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', stored);
})();

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    const btn = document.getElementById('theme-toggle-btn');
    if (btn) btn.textContent = next === 'dark' ? '☀️ Light Mode' : '🌙 Dark Mode';
}

// Sidebar hamburger
function toggleSidebar() {
    document.querySelector('.sidebar').classList.toggle('open');
}

// Toast notifications
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `<span>${message}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

// Modal helpers
function openModal(id) {
    document.getElementById(id).classList.add('open');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('open');
}

// Close modal on overlay click
document.addEventListener('click', function (e) {
    if (e.target.classList.contains('modal-overlay')) {
        e.target.classList.remove('open');
    }
});

// Confirm delete helper
function confirmDelete(message, formOrFn) {
    if (!confirm(message || 'Are you sure you want to delete this?')) return false;
    if (typeof formOrFn === 'string') {
        document.getElementById(formOrFn).submit();
    } else if (typeof formOrFn === 'function') {
        formOrFn();
    }
    return true;
}

// Inline category edit
function initInlineEdit() {
    document.querySelectorAll('[data-inline-edit]').forEach(function (el) {
        el.addEventListener('click', function () {
            const txId = el.dataset.txId;
            const field = el.dataset.inlineEdit;
            const current = el.dataset.value || el.textContent.trim();
            // Show a quick select or input
            if (field === 'category') {
                // handled by inline form
                return;
            }
        });
    });
}

// Auto-show flashed messages as toasts
document.addEventListener('DOMContentLoaded', function () {
    const theme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', theme);
    const btn = document.getElementById('theme-toggle-btn');
    if (btn) btn.textContent = theme === 'dark' ? '☀️ Light Mode' : '🌙 Dark Mode';

    document.querySelectorAll('.flash-msg').forEach(function (el) {
        showToast(el.dataset.message, el.dataset.type || 'info');
    });

    initInlineEdit();
});

// Upload drag-and-drop
function initUploadArea(areaId, inputId) {
    const area = document.getElementById(areaId);
    const input = document.getElementById(inputId);
    if (!area || !input) return;

    area.addEventListener('click', () => input.click());
    area.addEventListener('dragover', e => { e.preventDefault(); area.classList.add('drag-over'); });
    area.addEventListener('dragleave', () => area.classList.remove('drag-over'));
    area.addEventListener('drop', e => {
        e.preventDefault();
        area.classList.remove('drag-over');
        if (e.dataTransfer.files.length) {
            input.files = e.dataTransfer.files;
            input.dispatchEvent(new Event('change'));
        }
    });
}

// Format currency
function formatAmount(amount, currency = 'MKD') {
    return new Intl.NumberFormat('mk-MK', {
        style: 'currency',
        currency: currency,
        minimumFractionDigits: 2
    }).format(amount);
}

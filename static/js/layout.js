document.getElementById('nav-toggle')?.addEventListener('click', function () {
    const nav = document.getElementById('site-nav');
    const is_open = nav.classList.toggle('open');

    this.setAttribute('aria-expanded', is_open);
});

function ensure_toast_container() {
    let container = document.getElementById('toast-container');

    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    return container;
}

function remove_toast(toast) {
    toast.classList.remove('toast-visible');
    toast.addEventListener('transitionend', () => toast.remove(), { once: true });
}

function show_toast(message, type = "info", duration = 4000) {
    const container = ensure_toast_container();
    const toast = document.createElement('div');

    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    toast.addEventListener('click', () => remove_toast(toast));

    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('toast-visible'));

    if (duration) {
        setTimeout(() => remove_toast(toast), duration);
    }
}
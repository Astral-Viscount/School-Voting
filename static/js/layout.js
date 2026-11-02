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

function show_confirm_toast(message) {
    return new Promise(resolve => {
        const container = ensure_toast_container();
        const toast = document.createElement('div');
        toast.className = 'toast toast-confirm';

        const text = document.createElement('p');
        text.className = 'toast-message';
        text.textContent = message;

        const actions = document.createElement('div');
        actions.className = 'toast-actions';

        const cancel_btn = document.createElement('button');
        cancel_btn.type = 'button';
        cancel_btn.className = 'btn outline small';
        cancel_btn.textContent = 'Cancel';

        const confirm_btn = document.createElement('button');
        confirm_btn.type = 'button';
        confirm_btn.className = 'btn danger small';
        confirm_btn.textContent = 'Confirm';

        const finish = (result) => {
            remove_toast(toast);
            resolve(result);
        };

        cancel_btn.addEventListener('click', () => finish(false));
        confirm_btn.addEventListener('click', () => finish(true));

        actions.append(cancel_btn, confirm_btn);
        toast.append(text, actions);
        container.appendChild(toast);

        requestAnimationFrame(() => toast.classList.add('toast-visible'));
    });
}

document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', async (event) => {
        if (form.dataset.confirmed === "true") return;

        event.preventDefault();
        const ok = await show_confirm_toast(form.dataset.confirm);

        if (ok) {
            form.dataset.confirmed = "true";
            form.requestSubmit();
        }
    });
});
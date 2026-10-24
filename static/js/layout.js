document.getElementById('nav-toggle')?.addEventListener('click', function () {
    const nav = document.getElementById('site-nav');
    const is_open = nav.classList.toggle('open');

    this.setAttribute('aria-expanded', is_open);
});
function handle_credential_response(response) {
    fetch(window.LOGIN_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential: response.credential })
    })
    .then(async res => {
        let data = {};
        try { data = await res.json(); } catch {}

        if (res.ok && data.success) {
            show_toast("Signed in! Redirecting…", "success", 1200);
            setTimeout(() => window.location = window.DASHBOARD_URL, 600);
        }
        else {
            show_toast(data.error || "Login failed. Please try again.", "error");
        }
    })
    .catch(err => {
        console.error("Network error:", err);
        show_toast("Server error. Please try again.", "error");
    });
}
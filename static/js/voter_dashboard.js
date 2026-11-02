const csrf_token = document.querySelector('meta[name="csrf-token"]').content;

document.querySelectorAll('.vote-btn').forEach(button => {
    button.addEventListener('click', () => {
        vote_for(
            button,
            button.dataset.voteUrl,
            button.dataset.candidateName,
            button.dataset.positionName
        );
    });
});

async function vote_for(button, url, candidate_name, position_name) {
    const confirmed = await show_confirm_toast(
        `Vote for ${candidate_name} as ${position_name}? You can't change your vote afterwards.`
    );

    if (!confirmed) return;

    button.disabled = true;

    try {
        const response = await fetch(url, {
            method: "POST",
            headers: { "X-CSRFToken": csrf_token }
        });

        let data = null;

        try { data = await response.json(); } catch {}

        if (response.ok && data?.success) {
            show_toast("Vote recorded. Thank you!", "success");
            setTimeout(() => window.location.reload(), 1200);
            return;
        }

        if (response.status === 403 && !data) {
            show_toast("Your session may have expired. Please refresh the page and try again.", "error");
        } else {
            show_toast(data?.error || "Something went wrong. Please refresh and try again.", "error");
        }
        
    } catch (error) {
        console.error("Vote request failed:", error);
        show_toast("Network error. Please check your connection and try again.", "error");
    }

    button.disabled = false;
}
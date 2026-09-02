/** @odoo-module **/

function applyFlipForFaces(rootEl) {
    const root = rootEl || document;
    const thumbs = root.querySelectorAll(".bambus-face-wrap");
    if (!thumbs.length) return;

    thumbs.forEach((wrap) => {
        const pop = wrap.querySelector(".bambus-face-pop");
        if (!pop) return;

        const row = wrap.closest(".bambus-timeline-row") || wrap.closest(".bambus-flip-scope") || wrap;
        const clear = () => row.classList.remove("bambus-flip", "bambus-pop-up", "bambus-pop-down");

        const compute = () => {
            // reset first
            row.classList.remove("bambus-flip", "bambus-pop-up", "bambus-pop-down");

            // force visible for measurement
            const prevDisplay = pop.style.display;
            const prevVis = pop.style.visibility;
            pop.style.display = "block";
            pop.style.visibility = "hidden";

            const rect = pop.getBoundingClientRect();

            pop.style.display = prevDisplay;
            pop.style.visibility = prevVis;

            const vw = window.innerWidth || document.documentElement.clientWidth;
            const vh = window.innerHeight || document.documentElement.clientHeight;

            // Right overflow -> flip left
            if (rect.right > vw - 8) {
                row.classList.add("bambus-flip");
            }

            // Now measure again if flipped would be ideal, but we keep it simple:
            // Top overflow -> show below; Bottom overflow -> show above
            // (These modes use centered positioning, so they work regardless of flip.)
            if (rect.top < 8) {
                row.classList.add("bambus-pop-down");
            } else if (rect.bottom > vh - 8) {
                row.classList.add("bambus-pop-up");
            }
        };


        // Recompute on hover/enter, and on resize/scroll
        wrap.addEventListener("mouseenter", compute);
        wrap.addEventListener("mouseleave", clear);

        // Touch support (tap to toggle preview state; optional)
        wrap.addEventListener("touchstart", compute, { passive: true });
    });
}

function installObservers() {
    // run once
    applyFlipForFaces(document);

    // watch for wizard content updates (Odoo replaces DOM)
    const mo = new MutationObserver((mutations) => {
        for (const m of mutations) {
            for (const node of m.addedNodes) {
                if (!(node instanceof HTMLElement)) continue;
                // only run if our timeline exists inside added subtree
                if (node.querySelector?.(".bambus-face-wrap") || node.classList?.contains("bambus-face-wrap")) {
                    applyFlipForFaces(node);
                }
            }
        }
    });
    mo.observe(document.body, { childList: true, subtree: true });

    // keep it correct on resize/scroll
    window.addEventListener("resize", () => applyFlipForFaces(document), { passive: true });
    window.addEventListener("scroll", () => applyFlipForFaces(document), { passive: true });
}

// Odoo backend DOM ready
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", installObservers);
} else {
    installObservers();
}

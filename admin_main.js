
      function dismissPromoModal() {
        document.getElementById("promoModal")?.remove();
        fetch("/admin/blogs/clear_promo", { method: "POST" });
      }
      function triggerWhatsAppPromoShare(title, slug) {
        const host = window.location.origin;
        const text = `📢 *NEW TECHNOLOGY INSIGHT FROM SurgeTechKnow!*\n\n"${title}"\n\nAvoid network exploits and secure your operations now. Check out the full audit analysis with interactive test labs:\n👉 ${host}/blog/${slug}`;
        window.open(`https://wa.me/254791204587?text=${encodeURIComponent(text)}`, "_blank");
        dismissPromoModal();
      }
    
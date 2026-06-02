
function adminQuickSearch(q){
  q=(q||'').toLowerCase().trim();
  document.querySelectorAll('.tab-pane.active table tbody tr,.tab-pane.active .admin-media-item,.tab-pane.active .card-fire').forEach(el=>{
    if(!q){el.style.display='';return}
    el.style.display=(el.textContent||'').toLowerCase().includes(q)?'':'none';
  });
}

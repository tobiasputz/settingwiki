(()=>{document.querySelectorAll('[data-epoch]').forEach(el=>{const n=Number(el.dataset.epoch||0);if(n)el.textContent=new Date(n*1000).toLocaleString([], {dateStyle:'medium',timeStyle:'short'})})})();

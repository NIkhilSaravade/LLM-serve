// Runs before first paint so the chosen theme never flashes. Kept as an external file (not inline)
// because the Content-Security-Policy forbids inline script.
try {
  var t = localStorage.getItem('theme')
  if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t)
} catch (e) { /* storage blocked: keep the default */ }

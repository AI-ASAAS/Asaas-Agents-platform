(function () {
  var theme = 'light';
  try {
    if (localStorage.getItem('asaas-theme') === 'dark') theme = 'dark';
  } catch (e) {}
  document.documentElement.dataset.theme = theme;
})();

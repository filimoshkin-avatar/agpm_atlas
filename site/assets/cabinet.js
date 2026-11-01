/* Кабинет редактора: поведение, которое политика безопасности не даёт записать
   встроенными обработчиками (onchange, onclick). Подключается файлом с того же адреса. */
(function () {
  'use strict';
  document.addEventListener('change', e => {
    const el = e.target.closest('[data-autosubmit]');
    if (el && el.form) el.form.submit();
  });
  document.addEventListener('submit', e => {
    const form = e.target;
    const btn = e.submitter && e.submitter.closest('[data-confirm]');
    const msg = (btn && btn.dataset.confirm) || form.dataset.confirm;
    if (msg && !window.confirm(msg)) e.preventDefault();
  }, true);
})();

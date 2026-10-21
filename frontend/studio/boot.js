// Keep dependency failures visible even when the application module cannot load.
const connection = document.getElementById('connection');
const blocked = document.getElementById('blocked');
const retry = document.getElementById('retry');
const waitLabel = '页面模块仍在加载';
const waitCopy = '页面模块尚未完成加载。加载成功后会自动继续；如果长时间没有变化，可重新加载。浏览器中的本机草稿仍保留。';
const reloadFromBootWait = () => location.reload();
let waitingNoticeShown = false;
const waitHandle = setTimeout(() => {
  if (connection.textContent !== '正在连接本机服务…' || !blocked.classList.contains('hidden')) return;
  waitingNoticeShown = true;
  connection.textContent = waitLabel;
  connection.className = 'connection pending';
  blocked.classList.remove('hidden');
  blocked.dataset.bootWait = 'true';
  document.getElementById('blocked-title').textContent = '工作台仍在加载';
  document.getElementById('blocked-copy').textContent = waitCopy;
  retry.textContent = '重新加载页面';
  retry.onclick = reloadFromBootWait;
}, 8000);

import('./studio.js').then(() => {
  clearTimeout(waitHandle);
  if (waitingNoticeShown && retry.onclick === reloadFromBootWait) retry.onclick = null;
  if (waitingNoticeShown && blocked.dataset.bootWait === 'true') {
    blocked.dataset.bootWait = '';
    const stillOwnWaitNotice = connection.textContent === waitLabel && document.getElementById('blocked-copy').textContent === waitCopy;
    if (stillOwnWaitNotice) {
      blocked.classList.add('hidden');
      connection.textContent = '正在连接本机服务…';
      connection.className = 'connection pending';
    }
  }
}).catch(() => {
  clearTimeout(waitHandle);
  blocked.dataset.bootWait = '';
  connection.textContent = '页面模块加载失败';
  connection.className = 'connection error';
  blocked.classList.remove('hidden');
  document.getElementById('blocked-title').textContent = '工作台未能加载';
  document.getElementById('blocked-copy').textContent = '部分页面文件未能加载。请重新加载；本机草稿仍保留在此浏览器中。';
  retry.textContent = '重新加载页面';
  retry.onclick = () => location.reload();
});

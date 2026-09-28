const form = document.querySelector('#upload-form');
const input = document.querySelector('#archive');
const dropzone = document.querySelector('#dropzone');
const fileName = document.querySelector('#file-name');
const status = document.querySelector('#status');
const submitButton = document.querySelector('#submit-button');
const downloadLink = document.querySelector('#download-link');

function showStatus(message, isError = false) {
  status.hidden = false;
  status.textContent = message;
  status.classList.toggle('error', isError);
}

function updateFileName(file) {
  fileName.textContent = file ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB` : 'Ningún archivo seleccionado';
}

input.addEventListener('change', () => updateFileName(input.files[0]));
['dragenter', 'dragover'].forEach(type => dropzone.addEventListener(type, event => {
  event.preventDefault();
  dropzone.classList.add('dragging');
}));
['dragleave', 'drop'].forEach(type => dropzone.addEventListener(type, event => {
  event.preventDefault();
  dropzone.classList.remove('dragging');
}));
dropzone.addEventListener('drop', event => {
  const file = event.dataTransfer.files[0];
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  input.files = transfer.files;
  updateFileName(file);
});

form.addEventListener('submit', async event => {
  event.preventDefault();
  const file = input.files[0];
  if (!file) return showStatus('Selecciona primero un archivo ZIP.', true);
  if (!file.name.toLowerCase().endsWith('.zip')) return showStatus('El archivo debe tener formato .zip.', true);
  submitButton.disabled = true;
  downloadLink.hidden = true;
  showStatus('Procesando fotos y preparando el ZIP de salida…');
  try {
    const response = await fetch('/api/process', { method: 'POST', body: new FormData(form) });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error?.message || 'No se pudo procesar la exportación.');
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const summary = JSON.parse(response.headers.get('X-WhatsApp-Summary') || '{}');
    downloadLink.href = url;
    downloadLink.hidden = false;
    showStatus(`Listo: ${summary.processed || 0} fotos renombradas, ${summary.unchanged || 0} conservadas y ${summary.errors || 0} errores.`);
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    submitButton.disabled = false;
  }
});

// StudioAgent Frontend
const API_BASE = '/api';

// State
let currentJobId = null;
let ws = null;
let selectedFile = null;

// DOM elements
const uploadSection = document.getElementById('upload-panel');
const processingSection = document.getElementById('processing-section');
const resultsSection = document.getElementById('results-section');
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const uploadBtn = document.getElementById('upload-btn');
const progressFill = document.getElementById('progress-fill');
const progressText = document.getElementById('progress-text');
const progressPercent = document.getElementById('progress-percent');

// --- Drag & Drop ---
dropZone.addEventListener('click', () => fileInput.click());

dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('drag-over');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    if (e.dataTransfer.files.length) {
        selectedFile = e.dataTransfer.files[0];
        updateFileDisplay();
    }
});

fileInput.addEventListener('change', () => {
    selectedFile = fileInput.files[0];
    updateFileDisplay();
});

function updateFileDisplay() {
    if (selectedFile) {
        dropZone.querySelector('.drop-zone-content').innerHTML =
            `<p>Selected: <strong>${selectedFile.name}</strong></p>
             <p class="small">${(selectedFile.size / 1024 / 1024).toFixed(1)} MB</p>`;
        uploadBtn.disabled = false;
    }
}

// --- Upload ---
uploadBtn.addEventListener('click', async () => {
    if (!selectedFile) return;

    const formData = new FormData();
    formData.append('file', selectedFile);

    showSection('processing');
    updateProgress(5, 'Uploading video...');

    try {
        const response = await fetch(`${API_BASE}/upload`, {
            method: 'POST',
            body: formData,
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Upload failed');
        }

        const data = await response.json();
        currentJobId = data.job_id;
        connectWebSocket(data.job_id);
    } catch (err) {
        updateProgress(0, `Upload failed: ${err.message}`);
    }
});

// --- WebSocket Progress ---
function connectWebSocket(jobId) {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}${API_BASE}/ws/${jobId}`);

    ws.onmessage = (event) => {
        const job = JSON.parse(event.data);
        updateProgress(job.progress, job.current_step);

        // Show plan preview when available
        if (job.editing_plan && job.status === 'rendering') {
            showPlanPreview(job.editing_plan);
        }

        // Show results when complete
        if (job.status === 'completed') {
            showResults(job);
            ws.close();
        } else if (job.status === 'failed') {
            updateProgress(job.progress, `Error: ${job.error}`);
            ws.close();
        }
    };

    ws.onerror = () => {
        // Fallback to polling if WebSocket fails
        pollJobStatus(jobId);
    };
}

// --- Polling Fallback ---
async function pollJobStatus(jobId) {
    const interval = setInterval(async () => {
        try {
            const response = await fetch(`${API_BASE}/jobs/${jobId}`);
            const job = await response.json();
            updateProgress(job.progress, job.current_step);

            if (job.editing_plan && job.status === 'rendering') {
                showPlanPreview(job.editing_plan);
            }

            if (job.status === 'completed') {
                showResults(job);
                clearInterval(interval);
            } else if (job.status === 'failed') {
                updateProgress(job.progress, `Error: ${job.error}`);
                clearInterval(interval);
            }
        } catch (err) {
            // continue polling
        }
    }, 1500);
}

// --- UI Helpers ---
function updateProgress(percent, text) {
    progressFill.style.width = `${percent}%`;
    progressText.textContent = text;
    progressPercent.textContent = `${percent}%`;
}

function showResults(job) {
    showSection('results');

    // Video previews (stream endpoint serves inline without Content-Disposition)
    const preview16x9 = document.getElementById('preview-16x9');
    const preview9x16 = document.getElementById('preview-9x16');
    preview16x9.src = `${API_BASE}/jobs/${job.job_id}/stream/16x9`;
    preview9x16.src = `${API_BASE}/jobs/${job.job_id}/stream/9x16`;

    // Download links (download endpoint sets Content-Disposition: attachment)
    document.getElementById('download-16x9').href =
        `${API_BASE}/jobs/${job.job_id}/download/16x9`;
    document.getElementById('download-9x16').href =
        `${API_BASE}/jobs/${job.job_id}/download/9x16`;

    if (job.editing_plan) {
        document.getElementById('plan-json').textContent =
            JSON.stringify(job.editing_plan, null, 2);
    }
}

function showSection(name) {
    uploadSection.classList.add('hidden');
    processingSection.classList.add('hidden');
    resultsSection.classList.add('hidden');
    // upload → upload-panel, others → {name}-section
    const id = name === 'upload' ? 'upload-panel' : `${name}-section`;
    document.getElementById(id).classList.remove('hidden');
}

function showPlanPreview(plan) {
    const preview = document.getElementById('plan-preview');
    const content = document.getElementById('plan-content');
    preview.classList.remove('hidden');
    content.innerHTML = `
        <p><strong>Scenes:</strong> ${plan.scenes?.length || 0}</p>
        <p><strong>Subtitles:</strong> ${plan.subtitles?.length || 0}</p>
        <p><strong>Strategy:</strong> ${plan.summary || 'N/A'}</p>
    `;
}

// --- New Upload ---
document.getElementById('new-upload-btn')?.addEventListener('click', () => {
    selectedFile = null;
    currentJobId = null;
    fileInput.value = '';
    uploadBtn.disabled = true;
    dropZone.querySelector('.drop-zone-content').innerHTML =
        `<div class="icon">&#127909;</div>
         <p>Drag & drop your video here</p>
         <p class="small">or click to browse</p>
         <p class="small">Supports: MP4, MOV, AVI, WebM, MKV (max 500MB)</p>`;
    showSection('upload');
});

// --- Job History ---
async function loadHistory() {
    try {
        const response = await fetch(`${API_BASE}/jobs`);
        const data = await response.json();
        const jobList = document.getElementById('job-list');

        if (!data.jobs || data.jobs.length === 0) {
            jobList.innerHTML = '<p class="small" style="color:#666;">No jobs yet.</p>';
            return;
        }

        jobList.innerHTML = data.jobs.map(job => `
            <div class="job-item" data-job-id="${job.job_id}" style="cursor:pointer" title="Click to view">
                <span class="job-name">${job.job_id.substring(0, 8)}&#8230;</span>
                <span class="job-status status-${job.status}">${job.status}</span>
            </div>
        `).join('');

        // Attach click handlers
        jobList.querySelectorAll('.job-item').forEach(el => {
            el.addEventListener('click', () => resumeJob(el.dataset.jobId));
        });
    } catch (err) {
        // silent fail on history load
    }
}

async function resumeJob(jobId) {
    const response = await fetch(`${API_BASE}/jobs/${jobId}`);
    if (!response.ok) return;
    const job = await response.json();
    currentJobId = jobId;

    if (job.status === 'completed') {
        showResults(job);
    } else if (job.status === 'failed') {
        showSection('processing');
        updateProgress(job.progress, `Failed: ${job.error || 'unknown error'}`);
    } else {
        // Still running — reconnect to live updates
        showSection('processing');
        updateProgress(job.progress, job.current_step);
        connectWebSocket(jobId);
    }
}

loadHistory();

import os
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog

from django.conf import settings
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .forms import ProcessFolderForm
from . import ocr_core

# In-memory job store (single-process dev server only)
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _run_job(job_id: str, source: str, output: str):
    """Background thread: runs OCR processing and updates job state."""
    # Initialise OCR tools
    tesseract_cmd = getattr(settings, 'TESSERACT_CMD',
                            r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    font_path = getattr(settings, 'BENGALI_FONT_PATH',
                        r"F:\Scanned_Documents_Clean\fonts\NotoSansBengali-VariableFont_wdth,wght.ttf")
    ocr_core.setup_ocr(tesseract_cmd, font_path)

    supported = (".jpg", ".png", ".jpeg")
    total = sum(1 for f in os.listdir(source) if f.lower().endswith(supported))

    with _jobs_lock:
        _jobs[job_id].update({'total': total, 'current': 0, 'status': 'running'})

    def on_progress(current, total, filename):
        with _jobs_lock:
            _jobs[job_id]['current'] = current
            _jobs[job_id]['current_file'] = filename

    try:
        results = ocr_core.process_folder(source, output, progress_callback=on_progress)
        with _jobs_lock:
            _jobs[job_id].update({
                'status': 'done',
                'results': results,
                'output_folder': output,
            })
    except Exception as exc:
        with _jobs_lock:
            _jobs[job_id].update({'status': 'error', 'error': str(exc)})


def index(request):
    """Home page: show the processing form."""
    form = ProcessFolderForm()
    return render(request, 'processor/index.html', {'form': form})


def process(request):
    """Handle form submission: validate, start background job, redirect to status page."""
    if request.method != 'POST':
        return redirect('index')

    form = ProcessFolderForm(request.POST)
    if not form.is_valid():
        return render(request, 'processor/index.html', {'form': form})

    source = form.cleaned_data['source_folder']
    output = form.cleaned_data['output_folder'] or os.path.join(source, 'cleaned_pdf_files')

    import uuid
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            'status': 'starting',
            'source': source,
            'output': output,
            'total': 0,
            'current': 0,
            'current_file': '',
            'results': [],
            'error': None,
        }

    t = threading.Thread(target=_run_job, args=(job_id, source, output), daemon=True)
    t.start()

    return redirect('job_status', job_id=job_id)


def job_status(request, job_id):
    """Render the job progress / results page."""
    with _jobs_lock:
        job = dict(_jobs.get(job_id, {}))

    if not job:
        return render(request, 'processor/not_found.html', {'job_id': job_id})

    return render(request, 'processor/status.html', {'job': job, 'job_id': job_id})


@require_GET
def job_api(request, job_id):
    """JSON endpoint polled by JS for live progress updates."""
    with _jobs_lock:
        job = dict(_jobs.get(job_id, {}))

    if not job:
        return JsonResponse({'error': 'Job not found'}, status=404)

    return JsonResponse({
        'status': job.get('status'),
        'total': job.get('total', 0),
        'current': job.get('current', 0),
        'current_file': job.get('current_file', ''),
        'output_folder': job.get('output', ''),
        'results': job.get('results', []),
        'error': job.get('error'),
    })


@require_POST
def open_folder(request, job_id):
    """Open the output folder in Windows Explorer for the given job."""
    with _jobs_lock:
        job = dict(_jobs.get(job_id, {}))

    if not job:
        return JsonResponse({'error': 'Job not found'}, status=404)

    folder = job.get('output', '')
    if not folder or not os.path.isdir(folder):
        return JsonResponse({'error': f'Folder does not exist: {folder}'}, status=400)

    try:
        subprocess.Popen(['explorer', folder])
        return JsonResponse({'ok': True, 'folder': folder})
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=500)


@require_GET
def browse_folder(request):
    """Open a native folder-picker dialog (tkinter) on the server and return the chosen path.

    Only safe to use when the Django server is running locally on the same machine as the browser.
    """
    initial_dir = request.GET.get('initial', os.path.expanduser('~'))

    try:
        root = tk.Tk()
        root.withdraw()          # Hide the main Tk window
        root.attributes('-topmost', True)   # Bring dialog to front
        folder = filedialog.askdirectory(
            parent=root,
            title='Select Source Image Folder',
            initialdir=initial_dir,
            mustexist=True,
        )
        root.destroy()
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=500)

    if not folder:
        # User cancelled
        return JsonResponse({'cancelled': True, 'folder': ''})

    # Normalise to OS path separators
    folder = os.path.normpath(folder)
    return JsonResponse({'cancelled': False, 'folder': folder})

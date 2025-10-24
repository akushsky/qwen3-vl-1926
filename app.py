#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Kharkov-1926 Web Application
Flask-based web interface for the LLM pipeline
"""

import json
import os
import hashlib
import threading
import uuid
from typing import Dict, Any

from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
import requests

from kharkov1926_llm_pipeline_v6 import run_pipeline, run_batch, DEFAULT_ROIS

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['RESULTS_FOLDER'] = 'results'

# Ensure directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['RESULTS_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'JPG', 'JPEG', 'PNG'}

# In-memory job store for progress tracking
JOBS: Dict[str, Dict[str, Any]] = {}

# JROOTS API configuration (reuses CLI env names)
JROOTS_API = os.environ.get('JROOTS_API', 'https://jroots.co')
JROOTS_API_TOKEN = os.environ.get('JROOTS_API_TOKEN', '')
JROOTS_HEADERS = {'Authorization': f'Bearer {JROOTS_API_TOKEN}'} if JROOTS_API_TOKEN else {}
JROOTS_IMAGE_SOURCE_ID = os.environ.get('JROOTS_IMAGE_SOURCE_ID', 'kharkov1926')
JROOTS_VERIFY_SSL = os.environ.get('JROOTS_VERIFY_SSL', 'false').lower() == 'true'

def _sha512_of_file(path: str) -> str:
    h = hashlib.sha512()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def update_progress(session_id: str, percent: int, message: str):
    job = JOBS.get(session_id)
    if job is None:
        return
    job['progress'] = max(0, min(100, int(percent)))
    job['stage'] = message

def run_job(session_id: str, page1_path: str, page2_path: str, pad: float, overlay: bool, enforce_initials: bool):
    session_dir = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
    JOBS[session_id].update({
        'status': 'running',
        'progress': 5,
        'stage': 'started'
    })
    try:
        result = run_pipeline(
            page1_path,
            page2_path,
            outdir=session_dir,
            pad=pad,
            overlay=overlay,
            enforce_initials=enforce_initials,
            progress_cb=lambda p, m: update_progress(session_id, p, m)
        )
        # Save result
        result_file = os.path.join(session_dir, 'result.json')
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        JOBS[session_id].update({
            'status': 'done',
            'progress': 100,
            'stage': 'completed',
            'result_file': result_file
        })
    except Exception as e:
        JOBS[session_id].update({
            'status': 'error',
            'error': str(e)
        })

def run_batch_job(session_id: str, input_dir: str, pad: float, overlay: bool, enforce_initials: bool):
    JOBS[session_id].update({
        'status': 'running',
        'progress': 5,
        'stage': 'batch_started'
    })
    try:
        outdir = os.path.join(app.config['RESULTS_FOLDER'], session_id)
        result = run_batch(
            input_dir,
            outdir=outdir,
            pad=pad,
            overlay=overlay,
            enforce_initials=enforce_initials,
            roi_config=DEFAULT_ROIS,
            progress_cb=lambda p, m: update_progress(session_id, p, m)
        )
        # Save a consolidated result in the upload session folder for unified retrieval
        result_file = os.path.join(input_dir, 'result.json')
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        JOBS[session_id].update({
            'status': 'done',
            'progress': 100,
            'stage': 'completed',
            'result_file': result_file
        })
    except Exception as e:
        JOBS[session_id].update({
            'status': 'error',
            'error': str(e)
        })

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    try:
        if 'files' not in request.files:
            return jsonify({'error': 'No files uploaded'}), 400
        
        files = request.files.getlist('files')
        if len(files) < 2:
            return jsonify({'error': 'Please upload at least 2 files (page1 and page2)'}), 400
        
        # Create unique session directory
        session_id = str(uuid.uuid4())
        session_dir = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
        os.makedirs(session_dir, exist_ok=True)
        
        # Save uploaded files
        saved_files = []
        for i, file in enumerate(files[:2]):  # Only process first 2 files
            if file and allowed_file(file.filename):
                filename = secure_filename(f"page{i+1}_{file.filename}")
                filepath = os.path.join(session_dir, filename)
                file.save(filepath)
                saved_files.append(filepath)
        
        if len(saved_files) != 2:
            return jsonify({'error': 'Invalid file types. Please upload PNG or JPG images.'}), 400
        
        # Get processing options
        pad = float(request.form.get('pad', 0.02))
        overlay = request.form.get('overlay') == 'true'
        enforce_initials = request.form.get('enforce_initials') == 'true'
        # Initialize job
        JOBS[session_id] = {
            'status': 'queued',
            'progress': 0,
            'stage': 'queued'
        }
        # Start background thread
        t = threading.Thread(target=run_job, args=(session_id, saved_files[0], saved_files[1], pad, overlay, enforce_initials), daemon=True)
        t.start()

        return jsonify({
            'success': True,
            'session_id': session_id
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/progress/<session_id>')
def get_progress(session_id):
    job = JOBS.get(session_id)
    if not job:
        return jsonify({'error': 'Session not found'}), 404
    return jsonify({
        'session_id': session_id,
        'status': job.get('status'),
        'progress': job.get('progress', 0),
        'stage': job.get('stage', ''),
        'error': job.get('error')
    })

@app.route('/batch', methods=['POST'])
def upload_batch():
    try:
        if 'files' not in request.files:
            return jsonify({'error': 'No files uploaded'}), 400
        
        files = request.files.getlist('files')
        if len(files) < 2:
            return jsonify({'error': 'Please upload at least 2 files'}), 400
        
        # Create unique session directory
        session_id = str(uuid.uuid4())
        session_dir = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
        os.makedirs(session_dir, exist_ok=True)
        
        # Save all files
        saved_files = []
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(session_dir, filename)
                file.save(filepath)
                saved_files.append(filepath)
        
        if len(saved_files) < 2:
            return jsonify({'error': 'Invalid file types. Please upload PNG or JPG images.'}), 400
        
        # Get processing options
        pad = float(request.form.get('pad', 0.02))
        overlay = request.form.get('overlay') == 'true'
        enforce_initials = request.form.get('enforce_initials') == 'true'
        
        # Initialize job and run in background
        JOBS[session_id] = {
            'status': 'queued',
            'progress': 0,
            'stage': 'queued'
        }
        t = threading.Thread(target=run_batch_job, args=(session_id, session_dir, pad, overlay, enforce_initials), daemon=True)
        t.start()

        return jsonify({
            'success': True,
            'session_id': session_id
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/results/<session_id>')
def get_results(session_id):
    """Get results for a session"""
    session_dir = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
    result_file = os.path.join(session_dir, 'result.json')
    
    if not os.path.exists(result_file):
        return jsonify({'error': 'Results not found'}), 404
    
    with open(result_file, 'r', encoding='utf-8') as f:
        result = json.load(f)
    
    return jsonify(result)

@app.route('/download/<session_id>/<filename>')
def download_file(session_id, filename):
    """Download a specific file from a session"""
    session_dir = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
    file_path = os.path.join(session_dir, filename)
    
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    
    return send_file(file_path, as_attachment=True)

@app.route('/crops/<session_id>/<filename>')
def get_crop_image(session_id, filename):
    """Get crop images"""
    session_dir = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
    file_path = os.path.join(session_dir, filename)
    
    if not os.path.exists(file_path):
        return jsonify({'error': 'Crop image not found'}), 404
    
    return send_file(file_path)

@app.route('/export/jroots', methods=['POST'])
def export_jroots():
    try:
        payload = request.get_json(silent=True) or {}
        session_id = payload.get('session_id')
        entries = payload.get('entries') or []
        api_token_override = payload.get('api_token')
        default_image_source_id = payload.get('image_source_id') or JROOTS_IMAGE_SOURCE_ID
        default_image_key = payload.get('image_key') or ''
        default_image_path = payload.get('image_path') or ''
        default_price = str(payload.get('price') or '5000')
        if not session_id:
            return jsonify({'error': 'session_id is required'}), 400
        if not isinstance(entries, list) or not entries:
            return jsonify({'error': 'entries array is required'}), 400

        upload_root = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
        if not os.path.isdir(upload_root):
            return jsonify({'error': 'Upload session not found'}), 404

        successes = 0
        results = []

        # Prepare headers (allow per-request override)
        headers = dict(JROOTS_HEADERS)
        if api_token_override:
            headers['Authorization'] = f'Bearer {api_token_override}'

        for idx, entry in enumerate(entries):
            try:
                # Only process explicitly marked Jewish
                if not entry.get('is_jewish'):
                    results.append({'index': idx, 'skipped': True, 'reason': 'not_jewish'})
                    continue

                page1 = entry.get('page1') or ''
                text_content = entry.get('text_content') or ''
                price = str(entry.get('price') or default_price)
                image_source_id = entry.get('image_source_id') or default_image_source_id
                image_key = entry.get('image_key') or default_image_key or f'{session_id}:{page1}'
                image_path = entry.get('image_path') or default_image_path or f'/uploads/{session_id}/{page1}'

                if not page1:
                    results.append({'index': idx, 'error': 'missing page1 filename'})
                    continue

                img_path = os.path.join(upload_root, page1)
                if not os.path.isfile(img_path):
                    results.append({'index': idx, 'error': f'image not found: {page1}'})
                    continue

                # 1) Upload image (idempotent via sha512)
                sha = _sha512_of_file(img_path)
                img_data = {
                    'image_key': image_key,
                    'image_source_id': image_source_id,
                    'image_path': image_path,
                    'image_file_sha512': sha
                }
                with open(img_path, 'rb') as fp:
                    files = {'image_file': fp}
                    r = requests.post(f"{JROOTS_API}/api/admin/images", files=files, data=img_data,
                                      headers=headers, verify=JROOTS_VERIFY_SSL, timeout=30)
                    # Accept 200/201; allow 409 conflict as already exists
                    if r.status_code not in (200, 201):
                        try:
                            detail = r.json()
                        except Exception:
                            detail = {'text': r.text}
                        if r.status_code != 409:
                            results.append({'index': idx, 'error': 'image_upload_failed', 'status': r.status_code, 'detail': detail})
                            continue

                # 2) Create object tied to image sha
                obj_data = {
                    'image_file_sha512': sha,
                    'text_content': text_content,
                    'price': price
                }
                r2 = requests.post(f"{JROOTS_API}/api/admin/objects", data=obj_data,
                                   headers=headers, verify=JROOTS_VERIFY_SSL, timeout=30)
                if r2.status_code not in (200, 201):
                    try:
                        detail2 = r2.json()
                    except Exception:
                        detail2 = {'text': r2.text}
                    results.append({'index': idx, 'error': 'object_create_failed', 'status': r2.status_code, 'detail': detail2})
                    continue

                successes += 1
                results.append({'index': idx, 'ok': True, 'sha512': sha})

            except requests.RequestException as e:
                results.append({'index': idx, 'error': 'network_error', 'detail': str(e)})
            except Exception as e:
                results.append({'index': idx, 'error': 'unexpected_error', 'detail': str(e)})

        return jsonify({'success': True, 'uploaded': successes, 'results': results})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/jroots/image-sources', methods=['POST'])
def jroots_image_sources():
    try:
        payload = request.get_json(silent=True) or {}
        api_token = payload.get('api_token') or JROOTS_API_TOKEN
        headers = {'Authorization': f'Bearer {api_token}'} if api_token else {}
        r = requests.get(f"{JROOTS_API}/api/admin/image-sources", headers=headers, verify=JROOTS_VERIFY_SSL, timeout=30)
        if r.status_code != 200:
            try:
                detail = r.json()
            except Exception:
                detail = {'text': r.text}
            return jsonify({'error': 'failed_to_fetch_sources', 'status': r.status_code, 'detail': detail}), r.status_code
        return jsonify(r.json())
    except requests.RequestException as e:
        return jsonify({'error': 'network_error', 'detail': str(e)}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)


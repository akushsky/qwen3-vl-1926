#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Kharkov-1926 Web Application
Flask-based web interface for the LLM pipeline
"""

import os
import json
import tempfile
import shutil
import threading
from typing import Dict, Any
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
from werkzeug.utils import secure_filename
from kharkov1926_llm_pipeline_v6 import run_pipeline, run_batch, DEFAULT_ROIS, load_roi_config
import uuid

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
        
        # Process batch
        result = run_batch(
            session_dir,
            outdir=os.path.join(app.config['RESULTS_FOLDER'], session_id),
            pad=pad,
            overlay=overlay,
            enforce_initials=enforce_initials,
            roi_config=DEFAULT_ROIS
        )
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'result': result
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

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)


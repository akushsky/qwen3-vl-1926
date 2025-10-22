#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Kharkov-1926 Web Application
Flask-based web interface for the LLM pipeline
"""

import os
import json
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from kharkov1926_llm_pipeline_v6 import (
    run_pipeline,
    run_batch,
    DEFAULT_ROIS,
    load_roi_config,
    download_image_range,
    DEFAULT_USER_AGENT,
    classify_directory,
    pair_by_nearest,
    run_batch_from_pairs,
)
import uuid

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['RESULTS_FOLDER'] = 'results'

# Ensure directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['RESULTS_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'JPG', 'JPEG', 'PNG'}

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
        
        # Process the files
        result = run_pipeline(
            saved_files[0], 
            saved_files[1], 
            outdir=session_dir,
            pad=pad,
            overlay=overlay,
            enforce_initials=enforce_initials
        )
        
        # Save result
        result_file = os.path.join(session_dir, 'result.json')
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'result': result
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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

@app.route('/download', methods=['POST'])
def download_and_process():
    try:
        data = request.get_json(force=True, silent=False)
        if not isinstance(data, dict):
            return jsonify({'error': 'Invalid JSON payload'}), 400

        # Required numeric range
        start = data.get('start')
        end = data.get('end')
        if start is None or end is None:
            return jsonify({'error': 'start and end are required'}), 400
        try:
            start = int(start)
            end = int(end)
        except Exception:
            return jsonify({'error': 'start and end must be integers'}), 400
        if end < start:
            return jsonify({'error': 'end must be >= start'}), 400

        # Options
        url_template = data.get('url_template') or "https://e-resource.tsdavo.gov.ua/static/files/143/{i}.jpg"
        user_agent = data.get('user_agent') or DEFAULT_USER_AGENT
        sleep_min = float(data.get('sleep_min') or 1.0)
        sleep_max = float(data.get('sleep_max') or 5.0)
        timeout = int(data.get('timeout') or 30)
        retries = int(data.get('retries') or 2)
        resume = bool(data.get('resume') if data.get('resume') is not None else True)
        then_batch = bool(data.get('then_batch') or False)
        classify = bool(data.get('classify') or False)

        # Processing options for batch
        pad = float(data.get('pad') or 0.02)
        overlay = bool(data.get('overlay') or False)
        enforce_initials = bool(data.get('enforce_initials') or False)

        # Create session directories
        session_id = str(uuid.uuid4())
        session_dir = os.path.join(app.config['UPLOAD_FOLDER'], session_id)
        os.makedirs(session_dir, exist_ok=True)
        dl_dir = os.path.join(session_dir, 'downloads')
        os.makedirs(dl_dir, exist_ok=True)

        # Download
        dl_stats = download_image_range(
            start=start,
            end=end,
            url_template=url_template,
            dest_dir=dl_dir,
            user_agent=user_agent,
            sleep_min=sleep_min,
            sleep_max=sleep_max,
            timeout=timeout,
            retries=retries,
            resume=resume,
        )

        response = {
            'success': True,
            'session_id': session_id,
            'download': dl_stats
        }

        # Optionally classify and/or process batch
        if classify:
            cls_log = os.path.join(session_dir, '_classify.jsonl')
            cls = classify_directory(dl_dir, log_path=cls_log)
            response['classify'] = cls
            response['classify_log'] = os.path.relpath(cls_log, start=session_dir)
            if then_batch:
                pairs = pair_by_nearest(cls.get('classified', {}))
                result_dir = os.path.join(app.config['RESULTS_FOLDER'], session_id)
                os.makedirs(result_dir, exist_ok=True)
                result = run_batch_from_pairs(
                    pairs,
                    outdir=result_dir,
                    pad=pad,
                    overlay=overlay,
                    enforce_initials=enforce_initials,
                    roi_config=DEFAULT_ROIS
                )
                response['result'] = result
        elif then_batch:
            result_dir = os.path.join(app.config['RESULTS_FOLDER'], session_id)
            os.makedirs(result_dir, exist_ok=True)
            result = run_batch(
                dl_dir,
                outdir=result_dir,
                pad=pad,
                overlay=overlay,
                enforce_initials=enforce_initials,
                roi_config=DEFAULT_ROIS
            )
            response['result'] = result

        return jsonify(response)

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


#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Kharkov-1926 LLM-only pipeline (variant-aware, no local OCR)

- Detects form variant: Ukrainian ("ua") or Russian ("ru") from the page header (Qwen-VL).
- Variant-specific crops (percent-based):
    page1 -> nationality
    page1 -> head-of-family FIO (left crop)
    page2 -> surname+initials band (right crop)
- LLM calls:
    1) nationality (Jewish marker yes/no) with hardened prompt + post-filter sanity (force/annotate reason)
    2) right band → surname + initials (house owner = first row), initials normalized UA→RU
    3) left FIO → final FIO; initials are a SOFT hint; reconcile with left raw FIO if conflict
- Extras:
    * Overlays to QA crops
    * Batch mode over a folder of images (sorted pairing: (0,1), (2,3), ...)
    * Optional initials enforcement for patronymic (on mismatch -> null)
    * Optional ROI JSON config to override defaults
    * Manual review routing if is_jewish=false with confidence<1.0

Environment:
    LLM_ENDPOINT (default: http://127.0.0.1:8000/v1/chat/completions)
    LLM_MODEL    (default: Qwen/Qwen3-VL-8B-Instruct-FP8)
    OPENAI_API_KEY (default: EMPTY)
"""

import os, io, re, json, base64, argparse, glob, shutil
from typing import Dict, Any, Tuple, List
from PIL import Image, ImageDraw
import requests

# ----------------------------
# Config (env)
# ----------------------------
LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "http://127.0.0.1:8000/v1/chat/completions")
LLM_MODEL    = os.environ.get("LLM_MODEL",    "Qwen/Qwen3-VL-8B-Instruct-FP8")
API_KEY      = os.environ.get("OPENAI_API_KEY", "EMPTY")

# ----------------------------
# Default ROIs (percent of width/height) per variant
# ----------------------------
DEFAULT_ROIS = {
    "ua": {
        "page1": {
            # moved upward & left as requested
            "nationality": (0.10, 0.32, 0.45, 0.46),
            "fio_head":    (0.34, 0.33, 0.92, 0.48),
        },
        "page2": {
            "surname_band": (0.50, 0.12, 0.92, 0.88),
        }
    },
    "ru": {
        "page1": {
            # moved slightly left (x0: 0.10 → 0.08)
            "nationality": (0.08, 0.33, 0.48, 0.47),
            "fio_head":    (0.33, 0.32, 0.92, 0.47),
        },
        "page2": {
            "surname_band": (0.50, 0.12, 0.92, 0.88),
        }
    }
}

# Optional padding around each ROI (percent; applied symmetrically)
DEFAULT_PAD = 0.02

# ----------------------------
# Helpers
# ----------------------------
def ensure_dir(path: str):
    if path and not os.path.exists(path):
        os.makedirs(path, exist_ok=True)

def crop_percent(im: Image.Image, box_pct: Tuple[float,float,float,float], pad: float=0.0):
    """Crop a PIL image by percent box with optional padding. Returns (crop_img, (x0,y0,x1,y1) in px)."""
    w, h = im.size
    x0, y0, x1, y1 = box_pct
    if pad:
        x0 = max(0.0, x0 - pad); y0 = max(0.0, y0 - pad)
        x1 = min(1.0, x1 + pad); y1 = min(1.0, y1 + pad)
    X0, Y0, X1, Y1 = int(x0*w), int(y0*h), int(x1*w), int(y1*h)
    return im.crop((X0, Y0, X1, Y1)), (X0, Y0, X1, Y1)

def draw_overlays(page_img: Image.Image, rects_px: List[Tuple[int,int,int,int]], out_path: str):
    im = page_img.copy()
    d = ImageDraw.Draw(im)
    for (x0,y0,x1,y1) in rects_px:
        d.rectangle([x0,y0,x1,y1], outline=(0,0,0), width=4)
    im.save(out_path, quality=92)

def b64_image(img: Image.Image, fmt="JPEG", quality=92) -> str:
    """Encode PIL image to base64 data URL (JPEG/PNG)."""
    bio = io.BytesIO()
    if fmt.upper() == "JPEG":
        img.save(bio, format="JPEG", quality=quality)
        mime = "image/jpeg"
    else:
        img.save(bio, format="PNG")
        mime = "image/png"
    b64 = base64.b64encode(bio.getvalue()).decode("ascii")
    return f"data:{mime};base64,{b64}"

def call_vllm(messages: list, temperature: float=0.0, max_tokens: int=128, timeout: int=180) -> str:
    """OpenAI-compatible /v1/chat/completions call. Returns raw assistant content string."""
    payload = {"model": LLM_MODEL, "temperature": temperature, "max_tokens": max_tokens, "messages": messages}
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    r = requests.post(LLM_ENDPOINT, headers=headers, json=payload, timeout=timeout)
    r.raise_for_status()
    out = r.json()
    return out["choices"][0]["message"]["content"]

def parse_json_or_extract(text: str) -> Dict[str, Any]:
    """Parse JSON; if wrapped, extract the first {...} block. On failure, return debug info."""
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return {"error": "bad_json", "raw_content": text}

# ----------------------------
# Initials normalization (UA→RU, take first Cyrillic letter)
# ----------------------------
CYR_LETTERS = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯІЇЄҐ"
UA2RU = str.maketrans({"І":"И","Ї":"И","Є":"Е","Ґ":"Г"})

def normalize_initial_str(s: str) -> str:
    """Map UA→RU, strip non-letters, return FIRST Cyrillic uppercase letter (or '')."""
    if not s:
        return ""
    s = s.upper().translate(UA2RU)
    s = "".join(ch for ch in s if ch in CYR_LETTERS)
    return s[0] if s else ""

def normalize_initials_dict(initials: dict) -> dict:
    if not isinstance(initials, dict):
        return {"name":"", "patronymic":""}
    return {
        "name": normalize_initial_str(initials.get("name") or ""),
        "patronymic": normalize_initial_str(initials.get("patronymic") or "")
    }

# ----------------------------
# Post-fix for nationality sanity (force true/false + reason)
# ----------------------------
NON_JEWISH_MARKERS = [
    "укр", "укра", "рус", "рос", "бел", "поля", "арм", "тат", "груз", "нем",
    "лат", "лит", "азер", "узб", "турк", "гре", "молд", "кара", "осет", "даг",
    "чеч", "болг", "кирг", "каз", "евен", "бур", "морд", "мар"
]
JEWISH_MARKERS = ["евр", "євр", "иуд"]

def fix_nationality_sanity(nat: dict) -> dict:
    """Force is_jewish True/False for obvious markers; annotate 'reason'."""
    if not isinstance(nat, dict):
        return nat
    match = (nat.get("match") or "").lower().strip()
    if not match:
        return nat

    # Jewish markers → force true
    for j in JEWISH_MARKERS:
        if j in match:
            nat["is_jewish"] = True
            nat["confidence"] = 1.0
            nat["reason"] = {"forced_true_by_marker": j}
            return nat

    # Non-Jewish markers → force false
    for m in NON_JEWISH_MARKERS:
        if m in match:
            nat["is_jewish"] = False
            nat["confidence"] = 1.0
            nat["reason"] = {"forced_false_by_marker": m}
            return nat

    # Otherwise leave as is, but note we didn't override
    if "reason" not in nat:
        nat["reason"] = {"as_reported": True}
    return nat

# ----------------------------
# LLM Prompts
# ----------------------------
SYS_DETECT_VARIANT = (
    "На изображении верхняя часть бланка переписи 1926. Определи язык печатного заголовка:\n"
    "- Если «СІМЕЙНА КАРТКА», «ВСЕСОЮЗНИЙ ПЕРЕПИС НАСЕЛЕННЯ» — ответь ua.\n"
    "- Если «СЕМЕЙНАЯ КАРТА», «ВСЕСОЮЗНАЯ ПЕРЕПИСЬ НАСЕЛЕНИЯ» — ответь ru.\n"
    "Верни строго JSON: {\"variant\":\"ua\"|\"ru\",\"confidence\":0..1}."
)

# Hardened nationality prompt
SYS_NATIONALITY = (
    "Ты — аккуратный генеалогический ассистент. На изображении — короткая рукописная пометка национальности "
    "(на русском или украинском). Твоя цель — определить, указывает ли она ИМЕННО на еврейскую национальность.\n\n"
    "⚠️ ВАЖНО: пометки вроде «укр.», «рус.», «бел.», «поляк», «арм.», «тат.», «українець» и т.п. — это НЕ еврейские и должны давать is_jewish=false.\n"
    "Еврейские маркеры: «еврей», «евр.», «євр.», «иудей», «иуд.». Любое другое значение = false.\n\n"
    "Верни строго JSON: {\"is_jewish\": true|false, \"match\": \"найденная_строка_или_null\", \"confidence\": 0..1}."
)
USR_NATIONALITY = "Определи, указывает ли пометка на еврейскую национальность. Верни РОВНО JSON."

SYS_INITIALS = (
    "На изображении — правая вырезка (страница 2, список семьи). Первая строка — ГЛАВА СЕМЬИ. "
    "Сними с НЕЁ фамилию и инициалы (имени и отчества). Верни строго JSON: "
    "{\"surname\":\"...\",\"initials\":{\"name\":\"И|null\",\"patronymic\":\"М|null\"}}. Только кириллица."
)
USR_INITIALS = "Выдели фамилию и инициалы из первой строки. Верни РОВНО JSON."

# SOFT initials rule; JSON braces escaped for .format
SYS_FIO = (
    "Изображение — ЛЕВАЯ вырезка (страница 1): строка с полным ФИО главы семьи. "
    "Дано подсказкой с правой вырезки (стр.2): фамилия ≈ «{surname_right}», инициалы: имя = «{init_name}», отчество = «{init_patronymic}».\n"
    "Нормализация инициалов: допускаются украинские буквы, перед применением приведи в русские: І→И, Ї→И, Є→Е, Ґ→Г. "
    "Пиши ТОЛЬКО на русском (кириллица RU). Ё→Е допустимо.\n"
    "Правила:\n"
    "1) Фамилию считывай ПРЕЖДЕ ВСЕГО со ЛЕВОЙ вырезки (она крупнее). Правую фамилию используй как мягкую проверку формы ПЕРВОЙ БУКВЫ и общих биграмм.\n"
    "2) Инициалы с правой вырезки — МЯГКАЯ ПОДСКАЗКА. Если левая вырезка чётко даёт имя/отчество, ОТДАЙ ПРИОРИТЕТ ЛЕВОЙ вырезке, даже если инициалы отличаются.\n"
    "3) Если левая вырезка нечитабельна, тогда ориентируйся на инициалы. Избегай OCR-искажений типа «Альбя».\n"
    "Верни СТРОГО JSON UTF-8 без комментариев:\n"
    "{{\"surname\":\"...\",\"name\":\"...\",\"patronymic\":\"...|null\",\n"
    "  \"raw\":{{\"fio_left\":\"...|null\"}},\n"
    "  \"hints\":{{\"surname_right\":\"{surname_right}\",\"initials\":{{\"name\":\"{init_name}\",\"patronymic\":\"{init_patronymic}\"}}}},\n"
    "  \"surname_source\":\"left|right|blend\",\n"
    "  \"confidence\":0..1}}"
)
USR_FIO = (
    "Прочитай ФИО слева. Фамилию бери прежде всего слева; правую используй как подсказку (особенно для первой буквы). "
    "Имя/отчество — по нормализованным инициалам (UA→RU) только если слева неразборчиво. При сомнении отчества верни null. Верни РОВНО JSON по схеме."
)

# ----------------------------
# LLM steps
# ----------------------------
def step_detect_variant(top_crop: Image.Image) -> Dict[str, Any]:
    messages = [
        {"role": "system", "content": SYS_DETECT_VARIANT},
        {"role": "user", "content": [
            {"type":"text","text":"Определи язык печатного заголовка: ua или ru. Верни РОВНО JSON."},
            {"type":"image_url","image_url":{"url": b64_image(top_crop)}}
        ]}
    ]
    content = call_vllm(messages, temperature=0.0, max_tokens=32)
    return parse_json_or_extract(content)

def step_nationality(img_cropped: Image.Image) -> Dict[str, Any]:
    messages = [
        {"role": "system", "content": SYS_NATIONALITY},
        {"role": "user", "content": [
            {"type": "text", "text": USR_NATIONALITY},
            {"type": "image_url", "image_url": {"url": b64_image(img_cropped)}}
        ]}
    ]
    content = call_vllm(messages, temperature=0.0, max_tokens=64)
    return parse_json_or_extract(content)

def step_initials_right(img_cropped: Image.Image) -> Dict[str, Any]:
    messages = [
        {"role": "system", "content": SYS_INITIALS},
        {"role": "user", "content": [
            {"type": "text", "text": USR_INITIALS},
            {"type": "image_url", "image_url": {"url": b64_image(img_cropped)}}
        ]}
    ]
    content = call_vllm(messages, temperature=0.0, max_tokens=64)
    return parse_json_or_extract(content)

def step_fio_left(img_cropped: Image.Image, surname_right: str, init_name: str, init_patr: str) -> Dict[str, Any]:
    sys_prompt = SYS_FIO.format(
        surname_right=surname_right or "",
        init_name=init_name or "null",
        init_patronymic=init_patr or "null"
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": [
            {"type": "text", "text": USR_FIO},
            {"type": "image_url", "image_url": {"url": b64_image(img_cropped)}}
        ]}
    ]
    content = call_vllm(messages, temperature=0.0, max_tokens=180)
    return parse_json_or_extract(content)

# ----------------------------
# Variant-aware cropping
# ----------------------------
def get_rois(variant: str, roi_config: Dict[str, Any]) -> Dict[str, Any]:
    base = roi_config.get(variant) or roi_config["ua"]
    return base

def detect_variant_from_page1(im1: Image.Image) -> Dict[str, Any]:
    # header crop (center top band)
    hdr_crop, hdr_box = crop_percent(im1, (0.20, 0.03, 0.80, 0.13), pad=0.0)
    det = step_detect_variant(hdr_crop)
    variant = det.get("variant") if isinstance(det, dict) else None
    if variant not in ("ua","ru"):
        variant = "ua"  # safe default
    return {"variant": variant, "confidence": det.get("confidence", None), "hdr_box": hdr_box}

# ----------------------------
# Reconciliation helpers (prefer left FIO if initials conflict)
# ----------------------------
def split_fio_left(raw: str):
    """Return (surname, name, patronymic) if looks like 3 tokens, else None."""
    if not raw or not isinstance(raw, str):
        return None
    toks = re.findall(r"[А-ЯЁІЇЄҐа-яёіїєґ\-]+", raw)
    if len(toks) >= 3:
        return toks[0], toks[1], toks[2]
    return None

def initials_of_two(name: str, patr: str):
    """Return initials (RU) of name and patronymic."""
    def first_cyr(s: str):
        return normalize_initial_str(s or "")
    return first_cyr(name), first_cyr(patr)

# ----------------------------
# Single pair runner
# ----------------------------
def run_pipeline(page1_path: str, page2_path: str, outdir: str="./crops",
                 pad: float=DEFAULT_PAD, overlay: bool=False,
                 enforce_initials: bool=False, roi_config: Dict[str, Any]=None) -> Dict[str, Any]:
    ensure_dir(outdir)
    im1 = Image.open(page1_path)
    im2 = Image.open(page2_path)

    roi_cfg = roi_config if roi_config else DEFAULT_ROIS

    # Detect form variant from page1 header
    det = detect_variant_from_page1(im1)
    variant = det["variant"]
    rois = get_rois(variant, roi_cfg)

    # 1) Crop ROIs (variant-specific)
    nat_img, nat_box   = crop_percent(im1, rois["page1"]["nationality"], pad)
    fio_img, fio_box   = crop_percent(im1, rois["page1"]["fio_head"],    pad)
    band_img, band_box = crop_percent(im2, rois["page2"]["surname_band"], pad)

    # Save crops
    p_nat  = os.path.join(outdir, f"{variant}_page1_nationality.jpg");   nat_img.save(p_nat, quality=95)
    p_fio  = os.path.join(outdir, f"{variant}_page1_fio_head.jpg");      fio_img.save(p_fio, quality=95)
    p_band = os.path.join(outdir, f"{variant}_page2_surname_band.jpg");  band_img.save(p_band, quality=95)

    # Optional overlays
    if overlay:
        draw_overlays(im1, [det["hdr_box"], nat_box, fio_box], os.path.join(outdir, f"{variant}_page1_overlay.jpg"))
        draw_overlays(im2, [band_box],                         os.path.join(outdir, f"{variant}_page2_overlay.jpg"))

    # 2) LLM: nationality + sanity
    nationality = step_nationality(nat_img)
    nationality = fix_nationality_sanity(nationality)

    # Manual review flag: non-jewish & confidence < 1.0
    needs_manual_review = (
        isinstance(nationality, dict)
        and nationality.get("is_jewish") is False
        and float(nationality.get("confidence") or 0.0) < 1.0
    )

    # 3) LLM: right band -> surname + initials (normalize initials)
    right_raw = step_initials_right(band_img)
    r_surname = (right_raw.get("surname") or "").strip() if isinstance(right_raw, dict) else ""
    initials_raw = right_raw.get("initials") if isinstance(right_raw, dict) else None
    initials_norm = normalize_initials_dict(initials_raw)
    init_name = initials_norm["name"]
    init_patr = initials_norm["patronymic"]

    # 4) LLM: left FIO -> final (with SOFT initials hint)
    fio = step_fio_left(fio_img, r_surname, init_name, init_patr)

    # Optional post-check: enforce initials rule on patronymic
    if enforce_initials and isinstance(fio, dict):
        pat = fio.get("patronymic")
        if isinstance(pat, str) and init_patr and not pat.upper().startswith(init_patr):
            fio["patronymic"] = None  # better null than inconsistent

    # 4.5) Reconcile with left raw FIO; prefer left if initials conflict
    if isinstance(fio, dict):
        raw_left = (fio.get("raw") or {}).get("fio_left") or ""
        parsed = split_fio_left(raw_left)
        provided_init = {"name": init_name, "patronymic": init_patr}

        if parsed:
            left_sur, left_name, left_pat = parsed
            ln, lp = initials_of_two(left_name, left_pat)
            left_inits = {"name": ln, "patronymic": lp}
            fio.setdefault("checks", {})
            fio["checks"]["initials_provided"] = provided_init
            fio["checks"]["initials_left_raw"] = left_inits

            conflict = (
                (provided_init["name"] and left_inits["name"] and provided_init["name"] != left_inits["name"]) or
                (provided_init["patronymic"] and left_inits["patronymic"] and provided_init["patronymic"] != left_inits["patronymic"])
            )
            if conflict:
                fio["surname"] = left_sur
                fio["name"] = left_name
                fio["patronymic"] = left_pat if left_pat else fio.get("patronymic")
                fio["checks"]["resolution"] = "prefer_left_fio_due_to_initials_conflict"
            else:
                fio["checks"]["resolution"] = "ok_or_no_conflict"

    # 5) Assemble output
    result = {
        "inputs": {"page1": os.path.basename(page1_path), "page2": os.path.basename(page2_path)},
        "variant": {"detected": variant, "confidence": det.get("confidence")},
        "crops": {
            "header_band": {"box_percent": (0.20,0.03,0.80,0.13), "pixels": det["hdr_box"]},
            "page1_nationality": {"box_percent": rois["page1"]["nationality"], "pad": pad, "pixels": nat_box, "file": p_nat},
            "page1_fio_head":    {"box_percent": rois["page1"]["fio_head"],    "pad": pad, "pixels": fio_box, "file": p_fio},
            "page2_surname_band":{"box_percent": rois["page2"]["surname_band"],"pad": pad, "pixels": band_box, "file": p_band},
        },
        "llm": {"endpoint": LLM_ENDPOINT, "model": LLM_MODEL},
        "outputs": {
            "nationality": nationality,
            "right_band": {"raw": right_raw, "normalized": {"surname": r_surname, "initials": initials_norm}},
            "fio": fio
        },
        "flags": {
            "needs_manual_review": needs_manual_review
        }
    }

    # 6) Route to manual_review if needed
    if needs_manual_review:
        review_dir = os.path.join(outdir, "manual_review")
        ensure_dir(review_dir)
        for src in [page1_path, page2_path, p_nat, p_fio, p_band]:
            if os.path.exists(src):
                try:
                    shutil.copy2(src, review_dir)
                except Exception:
                    pass
        # write marker
        try:
            with open(os.path.join(review_dir, "README.txt"), "w", encoding="utf-8") as f:
                f.write("Flagged for manual review: is_jewish=false & confidence<1.0\n")
        except Exception:
            pass

    return result

# ----------------------------
# Batch mode
# ----------------------------
def discover_pairs(input_dir: str) -> List[Tuple[str,str]]:
    """Pair images in sorted order: (0,1), (2,3), ... Assumes order: page1 then page2."""
    exts = ("*.jpg","*.jpeg","*.png","*.JPG","*.JPEG","*.PNG")
    files: List[str] = []
    for ext in exts:
        files.extend(glob.glob(os.path.join(input_dir, ext)))
    files = sorted(files)
    pairs: List[Tuple[str,str]] = []
    for i in range(0, len(files), 2):
        if i+1 < len(files):
            pairs.append((files[i], files[i+1]))
    return pairs

def load_roi_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    for v in ("ua","ru"):
        if v not in cfg:
            raise ValueError(f"ROI config missing variant '{v}'")
    return cfg

def run_batch(input_dir: str, outdir: str, pad: float, overlay: bool, enforce_initials: bool, roi_config: Dict[str, Any]) -> Dict[str, Any]:
    ensure_dir(outdir)
    pairs = discover_pairs(input_dir)
    results = []
    for p1, p2 in pairs:
        pair_name = f"{os.path.splitext(os.path.basename(p1))[0]}__{os.path.splitext(os.path.basename(p2))[0]}"
        pair_outdir = os.path.join(outdir, pair_name)
        ensure_dir(pair_outdir)
        try:
            res = run_pipeline(p1, p2, outdir=pair_outdir, pad=pad, overlay=overlay,
                               enforce_initials=enforce_initials, roi_config=roi_config)
            results.append({"pair": [p1, p2], "result": res})
            with open(os.path.join(pair_outdir, "result.json"), "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=2)

            # copy flagged ones to central manual_review
            flags = (res or {}).get("flags") or {}
            if flags.get("needs_manual_review"):
                review_root = os.path.join(outdir, "manual_review")
                ensure_dir(review_root)
                dst_pair = os.path.join(review_root, os.path.basename(pair_outdir))
                try:
                    if not os.path.exists(dst_pair):
                        os.makedirs(dst_pair, exist_ok=True)
                    for name in os.listdir(pair_outdir):
                        src = os.path.join(pair_outdir, name)
                        if os.path.isfile(src):
                            shutil.copy2(src, dst_pair)
                except Exception as e:
                    results.append({"pair": [p1, p2], "manual_review_copy_error": str(e)})

        except Exception as e:
            results.append({"pair": [p1, p2], "error": str(e)})
    return {"count": len(results), "items": results}

# ----------------------------
# CLI
# ----------------------------
def main():
    ap = argparse.ArgumentParser("Kharkov-1926 LLM-only pipeline (variant-aware)")
    ap.add_argument("page1", nargs="?", help="Path to page 1 (questionnaire)")
    ap.add_argument("page2", nargs="?", help="Path to page 2 (family list)")
    ap.add_argument("--batch", help="Folder with images (process as consecutive pairs)", default=None)
    ap.add_argument("--outdir", default="./out", help="Output directory for results")
    ap.add_argument("--pad", type=float, default=DEFAULT_PAD, help="Padding percent around ROIs (default 0.02)")
    ap.add_argument("--overlay", action="store_true", help="Save overlay images for each pair")
    ap.add_argument("--enforce-initials", action="store_true",
                    help="If patronymic doesn't start with normalized initial, set it to null")
    ap.add_argument("--roi-config", help="Path to JSON with ROIs per variant (ua/ru) to override defaults", default=None)
    args = ap.parse_args()

    roi_config = DEFAULT_ROIS
    if args.roi_config:
        roi_config = load_roi_config(args.roi_config)

    if args.batch:
        res = run_batch(args.batch, outdir=args.outdir, pad=args.pad,
                        overlay=args.overlay, enforce_initials=args.enforce_initials, roi_config=roi_config)
    elif args.page1 and args.page2:
        res = run_pipeline(args.page1, args.page2, outdir=args.outdir, pad=args.pad,
                           overlay=args.overlay, enforce_initials=args.enforce_initials, roi_config=roi_config)
    else:
        ap.error("Provide either two images (page1 page2) or --batch <folder>")

    print(json.dumps(res, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

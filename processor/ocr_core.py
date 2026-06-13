import cv2
import numpy as np
import pytesseract
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os


def setup_ocr(tesseract_cmd, font_path):
    """Initialize Tesseract and register the Bengali font."""
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    if not pdfmetrics.getFont('NotoSansBengali') if _font_registered() else True:
        pdfmetrics.registerFont(TTFont('NotoSansBengali', font_path))


def _font_registered():
    """Check if font is already registered to avoid double-registration."""
    try:
        pdfmetrics.getFont('NotoSansBengali')
        return True
    except Exception:
        return False


def clean_scan(path):
    """Clean a scanned image: blur, threshold, deskew, denoise."""
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    img_blur = cv2.GaussianBlur(img, (5, 5), 0)
    img_eq = cv2.equalizeHist(img_blur)
    thresh = cv2.adaptiveThreshold(
        img_eq, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 35, 15
    )
    kernel = np.ones((2, 2), np.uint8)
    morph = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

    coords = np.column_stack(np.where(morph > 0))
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle

    (h, w) = morph.shape[:2]
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    deskewed = cv2.warpAffine(
        morph, M, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )
    final = cv2.medianBlur(deskewed, 3)
    return final


def ocr_to_pdf(image_path, pdf_path):
    """Run OCR on an image and save results as PDF + TXT."""
    text = pytesseract.image_to_string(image_path, lang="eng+ben")

    txt_path = f"{os.path.splitext(pdf_path)[0]}.txt"
    with open(txt_path, "w", encoding="utf-8") as output_file:
        output_file.write(text)

    pdf = canvas.Canvas(pdf_path, pagesize=letter)
    x, y = 50, 750
    pdf.setFont('NotoSansBengali', 14)

    for line in text.splitlines():
        if line.strip():
            pdf.drawString(x, y, line)
            y -= 15
        if y < 50:
            pdf.showPage()
            pdf.setFont("NotoSansBengali", 12)
            y = 750

    pdf.showPage()
    pdf.save()
    return txt_path


def process_folder(folder, out_folder, progress_callback=None):
    """
    Process all images in `folder`, write cleaned images and OCR PDFs to `out_folder`.

    Args:
        folder: str – source folder path
        out_folder: str – output folder path
        progress_callback: callable(current, total, filename) – optional progress hook

    Returns:
        list of dicts with keys: file, pdf, txt, status, error
    """
    os.makedirs(out_folder, exist_ok=True)
    supported = (".jpg", ".png", ".jpeg")
    files = [f for f in os.listdir(folder) if f.lower().endswith(supported)]
    total = len(files)
    results = []

    for idx, file in enumerate(files, start=1):
        img_path = os.path.join(folder, file)
        result = {'file': file, 'pdf': None, 'txt': None, 'status': 'ok', 'error': None}

        try:
            cleaned = clean_scan(img_path)
            out_img = os.path.join(out_folder, file)
            cv2.imwrite(out_img, cleaned)

            pdf_path = os.path.join(out_folder, os.path.splitext(file)[0] + ".pdf")
            txt_path = ocr_to_pdf(img_path, pdf_path)
            result['pdf'] = pdf_path
            result['txt'] = txt_path
        except Exception as exc:
            result['status'] = 'error'
            result['error'] = str(exc)

        results.append(result)

        if progress_callback:
            progress_callback(idx, total, file)

    return results

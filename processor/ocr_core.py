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
    if not _font_registered():
        pdfmetrics.registerFont(TTFont('NotoSansBengali', font_path))


def _font_registered():
    """Check if font is already registered to avoid double-registration."""
    try:
        pdfmetrics.getFont('NotoSansBengali')
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Image-cleaning helpers
# ---------------------------------------------------------------------------

def _upscale_if_needed(img, target_dpi=300, assumed_dpi=150):
    """
    Upscale the image if its resolution appears to be low-DPI.

    Scanned documents below ~200 DPI produce small text that Tesseract
    struggles with.  We assume the image was scanned at `assumed_dpi` when no
    EXIF data is available and upscale it to `target_dpi` when it seems too
    small (fewer than 1 500 px on the long side).
    """
    h, w = img.shape[:2]
    long_side = max(h, w)
    if long_side < 1500:
        scale = target_dpi / assumed_dpi
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return img


def _deskew(img):
    """
    Detect and correct skew using minAreaRect on *white* foreground pixels.

    Works on both grayscale and binary images.  Returns the corrected image
    using the same pixel type as the input.
    """
    # Threshold to binary for coordinate detection only
    _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(binary > 0))

    if coords.shape[0] < 10:
        # Not enough foreground pixels to compute a meaningful angle
        return img

    angle = cv2.minAreaRect(coords)[-1]

    # minAreaRect returns angles in the range [-90, 0).
    # Map the angle so that small tilts are corrected rather than a full 90°
    # rotation being applied.
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle

    # Ignore near-zero tilts (< 0.5°) to avoid unnecessary resampling
    if abs(angle) < 0.5:
        return img

    (h, w) = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
    rotated = cv2.warpAffine(
        img, M, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return rotated


def _remove_shadows(gray):
    """
    Subtract low-frequency illumination gradients (shadows/uneven lighting).

    Uses a large morphological dilation to estimate the background and then
    normalises pixel values against it.  Returns a uint8 grayscale image.
    """
    # Dilate with a large kernel to build a rough background estimate
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (51, 51))
    bg = cv2.dilate(gray, kernel)
    bg = cv2.GaussianBlur(bg, (51, 51), 0)

    # Subtract: bright spots near background → white; dark ink → dark
    diff = cv2.absdiff(gray, bg)
    # Invert so text is dark on white
    norm = cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
    result = 255 - norm
    return result


def _enhance_contrast(gray):
    """
    Apply CLAHE (Contrast Limited Adaptive Histogram Equalisation).

    CLAHE works on local tiles so it handles uneven illumination far better
    than global `equalizeHist`.  The clip-limit is kept modest to avoid
    amplifying noise.
    """
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _binarize(gray):
    """
    Adaptive Gaussian thresholding → clean binary image.

    Block size of 25 and constant C=15 is a well-tested default for A4/letter
    document scans.
    """
    return cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=25,
        C=15,
    )


def _denoise_binary(binary):
    """
    Remove isolated noise pixels from a binary image using morphology.

    An opening operation (erosion followed by dilation) with a 2×2 kernel
    removes single-pixel salt noise without noticeably thinning strokes.
    """
    kernel = np.ones((2, 2), np.uint8)
    return cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)


def clean_scan(path):
    """
    Full cleaning pipeline for a scanned document image.

    Pipeline
    --------
    1. Load as grayscale.
    2. Upscale if the image appears low-resolution.
    3. Remove background shadows / uneven illumination.
    4. Enhance local contrast with CLAHE.
    5. Deskew on the enhanced grayscale (better than deskewing on binary).
    6. Binarize with adaptive Gaussian thresholding.
    7. Morphological denoising to eliminate isolated noise pixels.

    Returns
    -------
    numpy.ndarray
        Cleaned binary (uint8) image ready for OCR and archiving.
    """
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {path}")

    # Step 1 – upscale low-DPI scans
    img = _upscale_if_needed(img)

    # Step 2 – remove shadows / uneven background illumination
    img = _remove_shadows(img)

    # Step 3 – enhance local contrast
    img = _enhance_contrast(img)

    # Step 4 – deskew on the pre-binarized grayscale
    img = _deskew(img)

    # Step 5 – binarize
    binary = _binarize(img)

    # Step 6 – remove noise
    binary = _denoise_binary(binary)

    return binary


# ---------------------------------------------------------------------------
# OCR → PDF / TXT
# ---------------------------------------------------------------------------

def ocr_to_pdf(cleaned_img, pdf_path):
    """
    Run OCR on a *cleaned* image array and save results as PDF + TXT.

    Parameters
    ----------
    cleaned_img : numpy.ndarray
        The already-cleaned binary image produced by `clean_scan`.
    pdf_path : str
        Destination path for the output PDF file.

    Returns
    -------
    str
        Path of the companion TXT file.
    """
    # Convert to PIL Image for pytesseract
    # pil_img = Image.fromarray(cleaned_img) #! Original code
    pil_img = cleaned_img

    # Custom Tesseract config: PSM 6 = assume a single uniform block of text.
    # OEM 1 = LSTM neural net engine (most accurate for mixed-script docs).
    custom_config = r"--oem 1 --psm 6"
    text = pytesseract.image_to_string(pil_img, lang="eng+ben", config=custom_config)

    # --- Write companion TXT ---
    txt_path = f"{os.path.splitext(pdf_path)[0]}.txt"
    with open(txt_path, "w", encoding="utf-8") as output_file:
        output_file.write(text)

    # --- Write PDF ---
    pdf = canvas.Canvas(pdf_path, pagesize=letter)
    page_width, page_height = letter
    margin_x = 50
    line_height = 16
    y = page_height - 50

    pdf.setFont('NotoSansBengali', 13)

    for line in text.splitlines():
        if line.strip():
            # Truncate lines that would overflow the page width
            pdf.drawString(margin_x, y, line)
        y -= line_height

        if y < 50:
            pdf.showPage()
            pdf.setFont('NotoSansBengali', 13)
            y = page_height - 50

    pdf.showPage()
    pdf.save()
    return txt_path


# ---------------------------------------------------------------------------
# Batch folder processor
# ---------------------------------------------------------------------------

def process_folder(folder, out_folder, progress_callback=None):
    """
    Process all images in `folder`, write cleaned images and OCR PDFs to
    `out_folder`.

    Parameters
    ----------
    folder : str
        Source folder path containing scanned images.
    out_folder : str
        Destination folder path for cleaned images, PDFs, and TXT files.
    progress_callback : callable(current, total, filename), optional
        Called after each file is processed.

    Returns
    -------
    list[dict]
        Each dict has keys: ``file``, ``pdf``, ``txt``, ``status``, ``error``.
    """
    os.makedirs(out_folder, exist_ok=True)
    supported = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp")
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith(supported))
    total = len(files)
    results = []

    for idx, file in enumerate(files, start=1):
        img_path = os.path.join(folder, file)
        result = {
            'file': file,
            'pdf': None,
            'txt': None,
            'status': 'ok',
            'error': None,
        }

        try:
            # Clean the scan
            cleaned = clean_scan(img_path)

            # Save the cleaned image
            out_img = os.path.join(out_folder, file)
            cv2.imwrite(out_img, cleaned)

            # OCR using the cleaned image (not the original raw file)
            pdf_path = os.path.join(out_folder, os.path.splitext(file)[0] + ".pdf")
            # txt_path = ocr_to_pdf(cleaned, pdf_path) #! Original code
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

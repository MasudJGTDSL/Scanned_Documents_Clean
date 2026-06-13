import cv2
import numpy as np
import pytesseract
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

import pytesseract

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
pdfmetrics.registerFont(TTFont('NotoSansBengali', r"F:\Scanned_Documents_Clean\fonts\NotoSansBengali-VariableFont_wdth,wght.ttf"))
# pdfmetrics.registerFont(TTFont('SolaimanLipi', 'SolaimanLipi.ttf'))

def clean_scan(path):
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    img_blur = cv2.GaussianBlur(img, (5, 5), 0)
    img_eq = cv2.equalizeHist(img_blur)
    thresh = cv2.adaptiveThreshold(img_eq, 255,
                                   cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, 35, 15)
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
    deskewed = cv2.warpAffine(morph, M, (w, h),
                              flags=cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_REPLICATE)
    final = cv2.medianBlur(deskewed, 3)
    return final

def ocr_to_pdf(image, pdf_path):
    text = pytesseract.image_to_string(image, lang="eng+ben")  # English + Bangla
    
    # Save as text file
    with open(f"{pdf_path.split('.')[0]}.txt", "w", encoding="utf-8") as output_file:
        output_file.write(text)
        
    pdf = canvas.Canvas(pdf_path, pagesize=letter)
    # Starting position
    x, y = 50, 750

    # Split text into lines
    pdf.setFont('NotoSansBengali', 14)
    for line in text.splitlines():
        if line.strip():  # skip empty lines
            pdf.drawString(x, y, line)
            y -= 15  # move down for next line

        # If page is full, start a new one
        if y < 50:
            pdf.showPage()
            pdf.setFont("NotoSansBengali", 12)
            y = 750
            
    # pdf.drawString(50, 750, text[:1000])  # simple placement
    pdf.showPage()
    pdf.save()

def process_folder(folder, out_folder):
    os.makedirs(out_folder, exist_ok=True)
    for file in os.listdir(folder):
        if file.lower().endswith((".jpg", ".png", ".jpeg")):
            img_path = os.path.join(folder, file)
            cleaned = clean_scan(img_path)
            out_img = os.path.join(out_folder, file)
            cv2.imwrite(out_img, cleaned)
            pdf_path = os.path.join(out_folder, file.split('.')[0] + ".pdf")
            ocr_to_pdf(img_path, pdf_path)

# process_folder("scans", "output")

#! To Run: python scanned_document_clean_and_OCR.py 

if __name__ == "__main__":
    # main()
    # multiple_md_file_to_html
    input_folder_path = r"E:\PRL Info"
    output_folder_path = rf"{input_folder_path}/cleaned_pdf_files"
    process_folder(input_folder_path, output_folder_path)
    

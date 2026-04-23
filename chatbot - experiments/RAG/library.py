from pypdf import PdfReader

# -----------------------------
# Extract text from PDF
# -----------------------------
def extract_text(pdf_path):
    reader = PdfReader(pdf_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)

# -----------------------------
# Chunk text
# -----------------------------
def chunk_text(text, chunk_size=500, overlap=100):
    chunks = []
    step = chunk_size - overlap

    for i in range(0, len(text), step):
        chunks.append(text[i:i + chunk_size])

    return chunks
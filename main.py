import os
import re
import shutil
from uuid import uuid4
from typing import Generator

from fastapi import FastAPI, Form, File, UploadFile, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import EmailStr

from starlette.middleware.sessions import SessionMiddleware

# --- CONFIGURATION & CONSTANTS ---
UPLOAD_BASE = "uploads"
IMAGE_DIR = os.path.join(UPLOAD_BASE, "images")
PDF_DIR = os.path.join(UPLOAD_BASE, "pdfs")
DATABASE_URL = "sqlite:///./contact_us.db"
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB Limit

# Ensure organized directory structure exists
for folder in [IMAGE_DIR, PDF_DIR]:
    os.makedirs(folder, exist_ok=True)

# --- DATABASE CORE ---
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class ContactEntry(Base):
    """Database model for storing contact form submissions."""
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    phone = Column(String)
    message = Column(String)
    image_path = Column(String)
    pdf_path = Column(String)

Base.metadata.create_all(bind=engine)

# --- APP INITIALIZATION ---
app = FastAPI(title="Professional Contact System")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/static", StaticFiles(directory="static"), name="static")
# Add Session Middleware (SumitProject is 'secret-key') for Flash Message
app.add_middleware(SessionMiddleware, secret_key="SumitProject")
templates = Jinja2Templates(directory="templates")

# --- DEPENDENCIES & UTILITIES ---
def get_db() -> Generator:
    """Dependency to provide a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def save_file(upload_file: UploadFile, destination_folder: str) -> str:
    """Saves an uploaded file with a unique UUID to prevent naming collisions."""
    ext = os.path.splitext(upload_file.filename)[1]
    filename = f"{uuid4()}{ext}"
    full_path = os.path.join(destination_folder, filename)
    
    with open(full_path, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    return full_path

# Helper to add messages to the session
def flash(request: Request, message: str, category: str = "success"):
    if "flash_messages" not in request.session:
        request.session["flash_messages"] = []
    request.session["flash_messages"].append({"message": message, "category": category})

# Helper to get and clear messages (for the template)
def get_flashed_messages(request: Request):
    return request.session.pop("flash_messages") if "flash_messages" in request.session else []

# Update Jinja2 configuration to make this helper available in all templates
templates.env.globals['get_flashed_messages'] = get_flashed_messages
# --- ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    """Renders the primary contact submission form."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/contact-submit/")
async def handle_form_submission(
    request: Request,
    name: str = Form(..., min_length=2, max_length=50),
    email: EmailStr = Form(...),
    phone: str = Form(...),
    message: str = Form(..., min_length=10, max_length=1000),
    image: UploadFile = File(...),
    pdf: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Handles validation, file storage, and database persistence for form data."""
    
    # 1. Validation Logic
    if not re.match(r"^\+?1?\d{9,15}$", phone):
        raise HTTPException(status_code=400, detail="Invalid phone format.")
    if not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Image file must be an image type.")
    if pdf.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="PDF file must be a PDF document.")

    # 2. File Persistence
    try:
        img_path = save_file(image, IMAGE_DIR)
        pdf_path = save_file(pdf, PDF_DIR)
    except Exception:
        raise HTTPException(status_code=500, detail="System error during file upload.")

    # 3. Database Persistence
    new_contact = ContactEntry(
        name=name, email=email, phone=phone,
        message=message, image_path=img_path, pdf_path=pdf_path
    )
    db.add(new_contact)
    db.commit()
    
    flash(request, "Your message has been sent successfully!", "success")
    return RedirectResponse(url="/view-details", status_code=303)

@app.get("/view-details", response_class=HTMLResponse)
async def dashboard_page(request: Request, db: Session = Depends(get_db)):
    """Displays a dashboard of all submitted contact entries."""
    contacts = db.query(ContactEntry).all()
    return templates.TemplateResponse("details.html", {"request": request, "contacts": contacts})

@app.post("/delete/{contact_id}")
async def remove_entry(contact_id: int, db: Session = Depends(get_db)):
    """Removes a record from the database and deletes its associated files."""
    entry = db.query(ContactEntry).filter(ContactEntry.id == contact_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found.")

    # Cleanup local storage
    for path in [entry.image_path, entry.pdf_path]:
        if path and os.path.exists(path):
            os.remove(path)

    db.delete(entry)
    db.commit()
    return RedirectResponse(url="/view-details", status_code=303)
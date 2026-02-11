import os
import re
import shutil
import json
from uuid import uuid4
from typing import Generator, List
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, Form, File, UploadFile, HTTPException, Depends, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import EmailStr
from starlette.middleware.sessions import SessionMiddleware
from datetime import datetime, timezone
from utils.mailer import send_contact_email # Import your new utility

# --- CONFIGURATION & CONSTANTS ---
UPLOAD_BASE = "uploads"
IMAGE_DIR = os.path.join(UPLOAD_BASE, "images")
PDF_DIR = os.path.join(UPLOAD_BASE, "pdfs")
DATABASE_URL = os.getenv("DATABASE_URL")
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB Limit
SECRET_KEY = os.getenv("SECRET_KEY")

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
    # New field to store list of filenames as a JSON string
    multiple_images = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    deleted_at = Column(DateTime, nullable=True) # None = Not deleted; Timestamp = Soft deleted

Base.metadata.create_all(bind=engine)

# --- APP INITIALIZATION ---
app = FastAPI(title="Professional Contact System")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/static", StaticFiles(directory="static"), name="static")
# Add Session Middleware (SumitProject is 'secret-key') for Flash Message
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
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
    background_tasks: BackgroundTasks,
    name: str = Form(..., min_length=2, max_length=50),
    email: EmailStr = Form(...),
    phone: str = Form(...),
    message: str = Form(..., min_length=10, max_length=1000),
    image: UploadFile = File(...),
    pdf: UploadFile = File(...),
    multiple_images: List[UploadFile] = File(None), # Accepts multiple files
    db: Session = Depends(get_db),
):
    """Handles validation, multi-file storage, and JSON database persistence."""
    
    # 1. Validation Logic
    if not re.match(r"^\+?1?\d{9,15}$", phone):
        raise HTTPException(status_code=400, detail="Invalid phone format.")
    if not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Profile image must be an image type.")
    if pdf.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Resume must be a PDF document.")

    # 2. File Persistence (Mandatory & Gallery)
    try:
        # Save single profile image and PDF
        img_path = save_file(image, IMAGE_DIR)
        pdf_path = save_file(pdf, PDF_DIR)

        # Save Multiple Gallery Images
        gallery_paths = []
        if multiple_images:
            for file in multiple_images:
                # Check if file is actually uploaded (filename exists)
                if file.filename:
                    # Professional Check: Validate each gallery file is an image
                    if not file.content_type.startswith("image/"):
                        continue # Skip non-image files
                    
                    saved_path = save_file(file, IMAGE_DIR)
                    gallery_paths.append(os.path.basename(saved_path))
                    
    except Exception as e:
        # Professional English comment: Log error and notify user
        raise HTTPException(status_code=500, detail="System error during file processing.")

    # 3. Database Persistence
    new_contact = ContactEntry(
        name=name, 
        email=email, 
        phone=phone,
        message=message, 
        image_path=img_path, 
        pdf_path=pdf_path,
        # Convert list of filenames to JSON string for easy future management
        multiple_images=json.dumps(gallery_paths) 
    )
    db.add(new_contact)
    db.commit()

    background_tasks.add_task(send_contact_email, email, name, message)
    
    flash(request, "Submission successful including gallery images!", "success")
    return RedirectResponse(url="/view-details", status_code=303)

@app.get("/view-details", response_class=HTMLResponse)
async def dashboard_page(request: Request, db: Session = Depends(get_db)):
    """Displays a dashboard of all submitted contact entries."""
    # contacts = db.query(ContactEntry).all()
    contacts = db.query(ContactEntry).filter(ContactEntry.deleted_at == None).all()
    return templates.TemplateResponse("details.html", {"request": request, "contacts": contacts})

@app.get("/view-detail/{contact_id}", response_class=HTMLResponse)
async def get_entry_detail(request: Request, contact_id: int, db: Session = Depends(get_db)):
    """
    Fetches a single contact entry by ID and renders the detailed view.
    """
    # 1. Fetch the record from the database
    entry = db.query(ContactEntry).filter(ContactEntry.id == contact_id).first()
    
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    # 2. Parse the JSON string back into a Python list for the gallery
    gallery_images = []
    if entry.multiple_images:
        try:
            gallery_images = json.loads(entry.multiple_images)
        except json.JSONDecodeError:
            gallery_images = []

    # 3. Render the specific detail template
    return templates.TemplateResponse(
        "view_single.html", 
        {
            "request": request, 
            "entry": entry, 
            "gallery": gallery_images
        }
    )

@app.post("/update/{contact_id}")
async def update_entry(
    request: Request,
    contact_id: int,
    message: str = Form(...),
    image: UploadFile = File(None), # Optional new profile image
    pdf: UploadFile = File(None),   # Optional new PDF
    delete_images: List[str] = Form(None), 
    new_gallery: List[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    entry = db.query(ContactEntry).filter(ContactEntry.id == contact_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    # 1. Update Profile Image (if a new one is uploaded)
    if image and image.filename:
        # Delete old file
        if os.path.exists(entry.image_path):
            os.remove(entry.image_path)
        # Save new file
        entry.image_path = save_file(image, IMAGE_DIR)

    # 2. Update PDF (if a new one is uploaded)
    if pdf and pdf.filename:
        # Delete old file
        if os.path.exists(entry.pdf_path):
            os.remove(entry.pdf_path)
        # Save new file
        entry.pdf_path = save_file(pdf, PDF_DIR)

    # 3. Manage Gallery Deletions
    current_gallery = json.loads(entry.multiple_images) if entry.multiple_images else []
    if delete_images:
        for img_name in delete_images:
            if img_name in current_gallery:
                current_gallery.remove(img_name)
                # Physical delete from uploads/images/
                file_path = os.path.join(IMAGE_DIR, img_name)
                if os.path.exists(file_path):
                    os.remove(file_path)

    # 4. Manage Gallery Additions
    if new_gallery:
        for file in new_gallery:
            if file.filename:
                saved_path = save_file(file, IMAGE_DIR)
                current_gallery.append(os.path.basename(saved_path))

    # 5. Update Remaining Fields
    entry.message = message
    entry.multiple_images = json.dumps(current_gallery)

    db.commit()
    flash(request, "Record and files updated successfully!", "success")
    return RedirectResponse(url="/view-details", status_code=303)

@app.get("/edit/{contact_id}", response_class=HTMLResponse)
async def edit_entry(request: Request, contact_id: int, db: Session = Depends(get_db)):
    entry = db.query(ContactEntry).filter(ContactEntry.id == contact_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    # Parse existing gallery for the template
    gallery = json.loads(entry.multiple_images) if entry.multiple_images else []
    
    return templates.TemplateResponse("edit.html", {
        "request": request, 
        "entry": entry, 
        "gallery": gallery
    })

@app.post("/delete/{contact_id}")
async def soft_delete_entry(request: Request, contact_id: int, db: Session = Depends(get_db)):
    entry = db.query(ContactEntry).filter(ContactEntry.id == contact_id).first()
    if entry:
        # Instead of deleting, we set the timestamp [cite: 2026-02-11]
        entry.deleted_at = datetime.now(timezone.utc)
        db.commit()
    return RedirectResponse(url="/view-details", status_code=303)


# async def remove_entry(contact_id: int, db: Session = Depends(get_db)):
#     """Removes a record from the database and deletes its associated files."""
#     entry = db.query(ContactEntry).filter(ContactEntry.id == contact_id).first()
#     if not entry:
#         raise HTTPException(status_code=404, detail="Entry not found.")

#     # Cleanup local storage
#     for path in [entry.image_path, entry.pdf_path]:
#         if path and os.path.exists(path):
#             os.remove(path)

#     db.delete(entry)
#     db.commit()
#     return RedirectResponse(url="/view-details", status_code=303)

@app.get("/view-trash", response_class=HTMLResponse)
async def view_trash(request: Request, db: Session = Depends(get_db)):
    # Fetch only the records that HAVE a deleted_at timestamp
    deleted_contacts = db.query(ContactEntry).filter(ContactEntry.deleted_at != None).all()
    
    return templates.TemplateResponse(
        "trash.html", 
        {"request": request, "contacts": deleted_contacts}
    )

@app.post("/restore/{contact_id}")
async def restore_entry(request: Request, contact_id: int, db: Session = Depends(get_db)):
    entry = db.query(ContactEntry).filter(ContactEntry.id == contact_id).first()
    if entry:
        entry.deleted_at = None  # Set back to None to make it "Active" again
        db.commit()
        flash(request, "Record restored successfully!", "success")
    return RedirectResponse(url="/view-trash", status_code=303)
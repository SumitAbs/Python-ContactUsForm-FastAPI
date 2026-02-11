import os
from fastapi.staticfiles import StaticFiles
import shutil
from typing import List
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from uuid import uuid4
from fastapi import FastAPI, Form, File, UploadFile, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import EmailStr, field_validator
import re

templates = Jinja2Templates(directory="templates")
# --- 1. SETUP DIRECTORIES ---
UPLOAD_BASE = "uploads"
IMAGE_DIR = os.path.join(UPLOAD_BASE, "images")
PDF_DIR = os.path.join(UPLOAD_BASE, "pdfs")

for folder in [IMAGE_DIR, PDF_DIR]:
    os.makedirs(folder, exist_ok=True)

# Ensure unique filenames to prevent overwriting
def save_upload_file(upload_file: UploadFile, folder: str) -> str:
    extension = os.path.splitext(upload_file.filename)[1]
    unique_filename = f"{uuid4()}{extension}" # Prevents collisions
    file_path = os.path.join(folder, unique_filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    return file_path

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB Limit

# --- 2. DATABASE SETUP (SQLite) ---
SQLALCHEMY_DATABASE_URL = "sqlite:///./contact_us.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class ContactEntry(Base):
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String)
    phone = Column(String)
    message = Column(String)
    image_path = Column(String)
    pdf_path = Column(String)

Base.metadata.create_all(bind=engine)

# --- 3. APP & DEPENDENCIES ---
app = FastAPI()

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- 4. THE CONTACT FORM LOGIC ---
# @app.post("/contact-submit/")
# async def submit_contact(
#     name: str = Form(..., min_length=2),
#     email: EmailStr = Form(...),
#     phone: str = Form(..., pattern=r"^\+?1?\d{9,15}$"), # Regex for phone
#     message: str = Form(..., max_length=500),
#     image: UploadFile = File(...),
#     pdf: UploadFile = File(...),
#     db: Session = Depends(get_db)
# ):
#     # Validation for File Types
#     if not image.content_type.startswith("image/"):
#         raise HTTPException(status_code=400, detail="File 'image' must be an image.")
#     if pdf.content_type != "application/pdf":
#         raise HTTPException(status_code=400, detail="File 'pdf' must be a PDF document.")

#     # Save Image
#     img_save_path = os.path.join(IMAGE_DIR, image.filename)
#     with open(img_save_path, "wb") as buffer:
#         shutil.copyfileobj(image.file, buffer)

#     # Save PDF
#     pdf_save_path = os.path.join(PDF_DIR, pdf.filename)
#     with open(pdf_save_path, "wb") as buffer:
#         shutil.copyfileobj(pdf.file, buffer)

#     # Save to SQLite
#     new_contact = ContactEntry(
#         name=name,
#         email=email,
#         phone=phone,
#         message=message,
#         image_path=img_save_path,
#         pdf_path=pdf_save_path
#     )
#     db.add(new_contact)
#     db.commit()
#     db.refresh(new_contact)

#     return {"status": "success", "data_id": new_contact.id}

@app.post("/contact-submit/")
async def submit_contact(
    name: str = Form(..., min_length=2, max_length=50),
    email: EmailStr = Form(...),
    phone: str = Form(...),
    message: str = Form(..., min_length=10, max_length=1000),
    image: UploadFile = File(...),
    pdf: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # 1. Phone Number Validation (Regex)
    if not re.match(r"^\+?1?\d{9,15}$", phone):
        raise HTTPException(status_code=400, detail="Invalid phone number format.")

    # 2. Image Validation
    if not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image.")
    
    # 3. PDF Validation
    if pdf.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF.")

    # 4. Save files using the helper (Categorized & Unique)
    try:
        img_path = save_upload_file(image, IMAGE_DIR)
        pdf_path = save_upload_file(pdf, PDF_DIR)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error saving files.")

    # 5. Save to Database
    new_entry = ContactEntry(
        name=name, email=email, phone=phone, 
        message=message, image_path=img_path, pdf_path=pdf_path
    )
    db.add(new_entry)
    db.commit()
    
    return RedirectResponse(url="/view-details", status_code=303)


# --- 5. GET DETAILS URL ---
@app.get("/contacts/")
async def get_all_contacts(db: Session = Depends(get_db)):
    return db.query(ContactEntry).all()

@app.get("/", response_class=HTMLResponse)
async def main(request: Request):
    """
    Renders the main contact form.
    """
    return templates.TemplateResponse("index.html", {"request": request})
    
@app.get("/view-details", response_class=HTMLResponse)
async def view_details(request: Request, db: Session = Depends(get_db)):
    """
    Fetches contacts from the database and renders the separate details.html file.
    """
    contacts = db.query(ContactEntry).all()
    # We pass the 'contacts' list directly to the template
    return templates.TemplateResponse(
        "details.html", 
        {"request": request, "contacts": contacts}
    )

@app.post("/delete/{contact_id}")
async def delete_contact(contact_id: int, db: Session = Depends(get_db)):
    """
    Deletes a contact record from the database and removes 
    the associated files from the local storage.
    """
    # Find the record
    contact = db.query(ContactEntry).filter(ContactEntry.id == contact_id).first()
    
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    # 1. Delete the physical files if they exist
    for file_path in [contact.image_path, contact.pdf_path]:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

    # 2. Delete the database record
    db.delete(contact)
    db.commit()

    # Redirect back to the details page
    return HTMLResponse(content="<script>window.location.href='/view-details';</script>")


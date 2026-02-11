import os
from fastapi.staticfiles import StaticFiles
import os
import shutil
from typing import List
from fastapi import FastAPI, Form, File, UploadFile, HTTPException, Depends
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import EmailStr
from fastapi.responses import HTMLResponse


# --- 1. SETUP DIRECTORIES ---
UPLOAD_BASE = "uploads"
IMAGE_DIR = os.path.join(UPLOAD_BASE, "images")
PDF_DIR = os.path.join(UPLOAD_BASE, "pdfs")

for folder in [IMAGE_DIR, PDF_DIR]:
    os.makedirs(folder, exist_ok=True)

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
@app.post("/contact-submit/")
async def submit_contact(
    name: str = Form(..., min_length=2),
    email: EmailStr = Form(...),
    phone: str = Form(..., pattern=r"^\+?1?\d{9,15}$"), # Regex for phone
    message: str = Form(..., max_length=500),
    image: UploadFile = File(...),
    pdf: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # Validation for File Types
    if not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File 'image' must be an image.")
    if pdf.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="File 'pdf' must be a PDF document.")

    # Save Image
    img_save_path = os.path.join(IMAGE_DIR, image.filename)
    with open(img_save_path, "wb") as buffer:
        shutil.copyfileobj(image.file, buffer)

    # Save PDF
    pdf_save_path = os.path.join(PDF_DIR, pdf.filename)
    with open(pdf_save_path, "wb") as buffer:
        shutil.copyfileobj(pdf.file, buffer)

    # Save to SQLite
    new_contact = ContactEntry(
        name=name,
        email=email,
        phone=phone,
        message=message,
        image_path=img_save_path,
        pdf_path=pdf_save_path
    )
    db.add(new_contact)
    db.commit()
    db.refresh(new_contact)

    return {"status": "success", "data_id": new_contact.id}

# --- 5. GET DETAILS URL ---
@app.get("/contacts/")
async def get_all_contacts(db: Session = Depends(get_db)):
    return db.query(ContactEntry).all()

@app.get("/", response_class=HTMLResponse)
async def main():
    with open("index.html", "r") as f:
        return f.read()
    
@app.get("/view-details", response_class=HTMLResponse)
async def view_details(db: Session = Depends(get_db)):
    contacts = db.query(ContactEntry).all()
    
    # Simple HTML Table Construction
    table_content = ""
    for c in contacts:
        table_content += f"""
        <tr>
            <td>{c.id}</td>
            <td>{c.name}</td>
            <td>{c.email}</td>
            <td>{c.phone}</td>
            <td>
                <a href='/{c.image_path}' target='_blank'>View Image</a>
            </td>
            <td>
                <a href='/{c.pdf_path}' target='_blank'>View PDF</a>
            </td>
            <td>
                <form action="/delete/{c.id}" method="post" style="display:inline;">
                    <button type="submit" onclick="return confirm('Are you sure?')">Delete</button>
                </form>
            </td>
        </tr>
        """
    
    html_template = f"""
    <html>
        <head>
            <style>
                table {{ width: 100%; border-collapse: collapse; }}
                th, td {{ padding: 10px; border: 1px solid #ddd; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <h2>Contact Submissions</h2>
            <table>
                <tr>
                    <th>ID</th>
                    <th>Name</th>
                    <th>Email</th>
                    <th>Phone</th>
                    <th>Image</th>
                    <th>PDF</th>
                    <th>Action</th>
                </tr>
                {table_content}
            </table>
            <br>
            <a href="/">Back to Form</a>
        </body>
    </html>
    """
    return html_template

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


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
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import EmailStr
from starlette.middleware.sessions import SessionMiddleware
from datetime import datetime, timezone
from utils.mailer import send_contact_email 
from utils.paystrax_helper import send_payment_request, send_3ds_request
import urllib.request
# --- CONFIGURATION & CONSTANTS ---
UPLOAD_BASE = "uploads"
IMAGE_DIR = os.path.join(UPLOAD_BASE, "images")
PDF_DIR = os.path.join(UPLOAD_BASE, "pdfs")
DATABASE_URL = os.getenv("DATABASE_URL")
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB Limit
SECRET_KEY = os.getenv("SECRET_KEY")

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
    multiple_images = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    deleted_at = Column(DateTime, nullable=True)

class PaymentLog(Base):
    """Database model for storing Paystrax transaction responses."""
    __tablename__ = "paystrax_logs"
    id = Column(Integer, primary_key=True, index=True)
    pay_id = Column(String)
    status_code = Column(String)
    status_desc = Column(String)
    amount = Column(String)
    full_response = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

Base.metadata.create_all(bind=engine)

# --- APP INITIALIZATION ---
app = FastAPI(title="Professional Contact & Payment System")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
templates = Jinja2Templates(directory="templates")

# --- DEPENDENCIES & UTILITIES ---
def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def save_file(upload_file: UploadFile, destination_folder: str) -> str:
    ext = os.path.splitext(upload_file.filename)[1]
    filename = f"{uuid4()}{ext}"
    full_path = os.path.join(destination_folder, filename)
    with open(full_path, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    return full_path

def flash(request: Request, message: str, category: str = "success"):
    if "flash_messages" not in request.session:
        request.session["flash_messages"] = []
    request.session["flash_messages"].append({"message": message, "category": category})

def get_flashed_messages(request: Request):
    return request.session.pop("flash_messages") if "flash_messages" in request.session else []

templates.env.globals['get_flashed_messages'] = get_flashed_messages

# --- CONTACT SYSTEM ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/contact-submit/")
async def handle_form_submission(
    request: Request, background_tasks: BackgroundTasks,
    name: str = Form(..., min_length=2, max_length=50),
    email: EmailStr = Form(...), phone: str = Form(...),
    message: str = Form(..., min_length=10, max_length=1000),
    image: UploadFile = File(...), pdf: UploadFile = File(...),
    multiple_images: List[UploadFile] = File(None), db: Session = Depends(get_db),
):
    if not re.match(r"^\+?1?\d{9,15}$", phone):
        raise HTTPException(status_code=400, detail="Invalid phone format.")
    
    img_path = save_file(image, IMAGE_DIR)
    pdf_path = save_file(pdf, PDF_DIR)
    
    gallery_paths = []
    if multiple_images:
        for file in multiple_images:
            if file.filename and file.content_type.startswith("image/"):
                saved_path = save_file(file, IMAGE_DIR)
                gallery_paths.append(os.path.basename(saved_path))
    
    new_contact = ContactEntry(
        name=name, email=email, phone=phone, message=message,
        image_path=img_path, pdf_path=pdf_path,
        multiple_images=json.dumps(gallery_paths)
    )
    db.add(new_contact)
    db.commit()
    
    background_tasks.add_task(send_contact_email, email, name, message)
    flash(request, "Submission successful!", "success")
    return RedirectResponse(url="/view-details", status_code=303)

@app.get("/view-details", response_class=HTMLResponse)
async def dashboard_page(request: Request, db: Session = Depends(get_db)):
    contacts = db.query(ContactEntry).filter(ContactEntry.deleted_at == None).all()
    return templates.TemplateResponse("details.html", {"request": request, "contacts": contacts})

@app.get("/view-detail/{contact_id}", response_class=HTMLResponse)
async def get_entry_detail(request: Request, contact_id: int, db: Session = Depends(get_db)):
    entry = db.query(ContactEntry).filter(ContactEntry.id == contact_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    gallery = json.loads(entry.multiple_images) if entry.multiple_images else []
    return templates.TemplateResponse("view_single.html", {"request": request, "entry": entry, "gallery": gallery})

@app.get("/edit/{contact_id}", response_class=HTMLResponse)
async def edit_entry(request: Request, contact_id: int, db: Session = Depends(get_db)):
    entry = db.query(ContactEntry).filter(ContactEntry.id == contact_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    gallery = json.loads(entry.multiple_images) if entry.multiple_images else []
    return templates.TemplateResponse("edit.html", {"request": request, "entry": entry, "gallery": gallery})

@app.post("/update/{contact_id}")
async def update_entry(
    request: Request, contact_id: int, message: str = Form(...),
    image: UploadFile = File(None), pdf: UploadFile = File(None),
    delete_images: List[str] = Form(None), new_gallery: List[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    entry = db.query(ContactEntry).filter(ContactEntry.id == contact_id).first()
    if not entry: raise HTTPException(status_code=404, detail="Entry not found")

    if image and image.filename:
        if os.path.exists(entry.image_path): os.remove(entry.image_path)
        entry.image_path = save_file(image, IMAGE_DIR)

    if pdf and pdf.filename:
        if os.path.exists(entry.pdf_path): os.remove(entry.pdf_path)
        entry.pdf_path = save_file(pdf, PDF_DIR)

    current_gallery = json.loads(entry.multiple_images) if entry.multiple_images else []
    if delete_images:
        for img_name in delete_images:
            if img_name in current_gallery:
                current_gallery.remove(img_name)
                f_path = os.path.join(IMAGE_DIR, img_name)
                if os.path.exists(f_path): os.remove(f_path)

    if new_gallery:
        for f in new_gallery:
            if f.filename: current_gallery.append(os.path.basename(save_file(f, IMAGE_DIR)))

    entry.message = message
    entry.multiple_images = json.dumps(current_gallery)
    db.commit()
    flash(request, "Record updated successfully!", "success")
    return RedirectResponse(url="/view-details", status_code=303)

@app.post("/delete/{contact_id}")
async def soft_delete_entry(request: Request, contact_id: int, db: Session = Depends(get_db)):
    entry = db.query(ContactEntry).filter(ContactEntry.id == contact_id).first()
    if entry:
        entry.deleted_at = datetime.now(timezone.utc)
        db.commit()
    return RedirectResponse(url="/view-details", status_code=303)

@app.get("/view-trash", response_class=HTMLResponse)
async def view_trash(request: Request, db: Session = Depends(get_db)):
    deleted_contacts = db.query(ContactEntry).filter(ContactEntry.deleted_at != None).all()
    return templates.TemplateResponse("trash.html", {"request": request, "contacts": deleted_contacts})

@app.post("/restore/{contact_id}")
async def restore_entry(request: Request, contact_id: int, db: Session = Depends(get_db)):
    entry = db.query(ContactEntry).filter(ContactEntry.id == contact_id).first()
    if entry:
        entry.deleted_at = None
        db.commit()
        flash(request, "Record restored successfully!", "success")
    return RedirectResponse(url="/view-trash", status_code=303)



#########################################################################################################
#########################################################################################################
#########################################################################################################
#########################################################################################################
#########################################################################################################
#########################################################################################################
#########################################################################################################

"""
    Simple Payment using Card Detais
"""
@app.get("/pay", response_class=HTMLResponse)
async def payment_page(request: Request):
    return templates.TemplateResponse("pay_form.html", {"request": request})

@app.post("/checkout")
async def handle_checkout(
    request: Request,
    holder: str = Form(...), number: str = Form(...),
    month: str = Form(...), year: str = Form(...),
    cvv: str = Form(...), amount: str = Form(...),
    brand: str = Form(...), db: Session = Depends(get_db)
):
    card_info = {
        "holder": holder, "number": number, "expiryMonth": month,
        "expiryYear": year, "cvv": cvv, "amount": amount, "paymentBrand": brand
    }
    
    api_res = send_payment_request(card_info)
    result_data = api_res.get('result', {})
    
    new_log = PaymentLog(
        pay_id=api_res.get('id', 'N/A'),
        status_code=result_data.get('code', 'Error'),
        status_desc=result_data.get('description', 'No description'),
        amount=amount,
        full_response=json.dumps(api_res)
    )
    db.add(new_log)
    db.commit()
    
    flash(request, f"Payment Logged: {result_data.get('description')}", "info")
    return {"status": "Database Updated", "gateway_response": api_res}

#########################################################################################################
#########################################################################################################
#########################################################################################################
#########################################################################################################
#########################################################################################################
#########################################################################################################
#########################################################################################################

"""
    PAYMENT LOGS
"""
@app.get("/payment-history", response_class=HTMLResponse)
async def view_payment_history(request: Request, db: Session = Depends(get_db)):
    logs = db.query(PaymentLog).order_by(PaymentLog.created_at.desc()).all()
    return templates.TemplateResponse("payment_dashboard.html", {"request": request, "logs": logs})

@app.get("/payment-detail/{log_id}", response_class=HTMLResponse)
async def view_single_payment(request: Request, log_id: int, db: Session = Depends(get_db)):
    """
    Ek specific payment ki poori detail aur API ka raw response dikhata hai.
    """
    log = db.query(PaymentLog).filter(PaymentLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Payment record not found")
    
    # JSON string ko wapas dictionary mein badalna taaki template mein sundar dikhe
    full_data = json.loads(log.full_response) if log.full_response else {}
    
    return templates.TemplateResponse(
        "payment_view_single.html", 
        {"request": request, "log": log, "full_data": full_data}
    )


#########################################################################################################
#########################################################################################################
#########################################################################################################
#########################################################################################################
#########################################################################################################
#########################################################################################################
#########################################################################################################

"""
    3D Security Starts
"""
# Form View
@app.get("/test-3ds-view", response_class=HTMLResponse)
async def view_test_3ds(request: Request):
    """
    Serves the specific 3DS testing template.
    Does not interfere with the standard /pay route.
    """
    return templates.TemplateResponse("test_3ds.html", {"request": request})

# Step 1: Initialize the 3DS Payment Request
@app.post("/checkout-3ds")
async def initiate_3ds_payment(request: Request, db: Session = Depends(get_db)):
    """
    Handles initial 3DS request and dynamically sets the callback for cloud environments.
    """
    form_data = await request.form()
    
    # Check if we are running in a GitHub Codespace or behind a proxy
    forwarded_host = request.headers.get("x-forwarded-host")
    forwarded_proto = request.headers.get("x-forwarded-proto", "https")
    
    if forwarded_host:
        # Use the public GitHub Codespace URL
        base_url = f"{forwarded_proto}://{forwarded_host}"
    else:
        # Fallback for local development
        base_url = str(request.base_url).rstrip('/')
    
    # This is the URL the bank will use to send the user back
    callback_endpoint = f"{base_url}/payment-callback"
    
    # LOG THIS: Check your terminal to see if this is a .github.dev URL
    print(f"--- DEBUG: CALLBACK URL IS {callback_endpoint} ---")
    
    api_response = send_3ds_request(dict(form_data), callback_endpoint)

    # Initial database log
    log_entry = PaymentLog(
        pay_id=api_response.get('id', 'N/A'),
        status_code=api_response.get('result', {}).get('code', 'PENDING_3DS'),
        status_desc="Awaiting 3DS Authentication",
        amount=form_data.get('amount'),
        full_response=json.dumps(api_response)
    )
    db.add(log_entry)
    db.commit()

    if "redirect" in api_response:
        redirect_url = api_response['redirect']['url']
        return RedirectResponse(url=redirect_url, status_code=303)
    
    return api_response

# Step 2: Final Verification after Bank Redirection
@app.get("/payment-callback")
async def handle_bank_redirection(id: str, db: Session = Depends(get_db)):
    """
    This route is triggered when the user returns from the bank page.
    It performs a final status check to confirm the payment was successful.
    """
    # Paystrax verification endpoint
    entity_id = "8ac7a4c86a304582016a30b41682019b"
    check_url = f"https://eu-test.oppwa.com/v1/payments/{id}?entityId={entity_id}"
    
    try:
        req = urllib.request.Request(check_url)
        # Professional Bearer Token usage
        req.add_header('Authorization', 'Bearer OGFjN2E0Yzg2YTMwNDU4MjAxNmEzMGI0MTZlMjAxOWZ8QmJkdXdacGg5TUhMbTV0dzplbkw=')
        
        with urllib.request.urlopen(req) as response:
            final_res = json.loads(response.read())

        # Extract results and update the existing database record
        result_data = final_res.get('result', {})
        status_code = result_data.get('code')
        status_desc = result_data.get('description')
        
        db.query(PaymentLog).filter(PaymentLog.pay_id == id).update({
            "status_code": status_code,
            "status_desc": status_desc,
            "full_response": json.dumps(final_res)
        })
        db.commit()

        # UI Response based on success or failure
        is_success = status_code.startswith("000")
        color = "#28a745" if is_success else "#dc3545"
        
        return HTMLResponse(content=f"""
            <div style="text-align:center; margin-top:100px; font-family: sans-serif;">
                <h1 style="color:{color};">{status_desc}</h1>
                <p>Transaction ID: {id}</p>
                <a href="/payment-history" style="color:#007bff; text-decoration:none;">Return to Dashboard</a>
            </div>
        """)

    except Exception as e:
        return {"error": "Verification Failed", "message": str(e)}
    

#########################################################################################################
#########################################################################################################
#########################################################################################################
#########################################################################################################
#########################################################################################################
#########################################################################################################
#########################################################################################################

"""
    PAYMENT VARIFICATION : PENDING STATUS
"""

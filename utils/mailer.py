import os
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

# Professional configuration from environment variables 
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
MAIL_FROM = os.getenv("MAIL_FROM")

def send_contact_email(user_email: str, user_name: str, message_body: str):
    """
    Constructs and sends a professional auto-response email. 
    """
    msg = EmailMessage()
    
    # Professional English Email Body 
    content = f"""
    Dear {user_name},

    Thank you for contacting us through our website. This is an automated 
    confirmation to let you know that we have received your message.

    Your Message:
    --------------------------------------------------
    {message_body}
    --------------------------------------------------

    Our team will review your submission and get back to you shortly.

    Best regards,
    Management Team
    """
    
    msg.set_content(content)
    msg['Subject'] = 'Message Received: Thank you for reaching out'
    msg['From'] = MAIL_FROM
    msg['To'] = user_email

    try:
        # Using context manager for safe connection handling 
        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
            server.starttls()  # Secure the connection
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        # In professional apps, failed emails shouldn't crash the server
        print(f"CRITICAL: Failed to send email to {user_email}. Error: {e}")
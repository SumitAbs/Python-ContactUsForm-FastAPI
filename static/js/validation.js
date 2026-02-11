/**
 * Contact Form Validation Module
 * Professional Vanilla JS logic for file and text verification.
 */
document.addEventListener('DOMContentLoaded', () => {
    const contactForm = document.getElementById('contactForm');
    if (!contactForm) return;

    contactForm.addEventListener('submit', function(event) {
        let isValid = true;
        const submitBtn = document.getElementById('submitBtn');

        // Reset error messages
        document.querySelectorAll('.error-msg').forEach(s => s.textContent = '');

        // 1. Input Extractions
        const name = document.getElementById('name').value.trim();
        const email = document.getElementById('email').value.trim();
        const phone = document.getElementById('phone').value.trim();
        const message = document.getElementById('message').value.trim();
        const imageInput = document.getElementById('image');
        const pdfInput = document.getElementById('pdf');
        const galleryInput = document.getElementById('multiple_images');
        
        const maxSize = 5 * 1024 * 1024; // 5MB
        const getExt = (fname) => fname.split('.').pop().toLowerCase();

        // 2. Text Validations
        if (name.length < 2) {
            setError('nameError', 'Full Name is required (min 2 chars).');
            isValid = false;
        }

        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            setError('emailError', 'Please provide a valid professional email.');
            isValid = false;
        }

        if (!/^\+?1?\d{9,15}$/.test(phone)) {
            setError('phoneError', 'Invalid phone format (9-15 digits).');
            isValid = false;
        }

        if (message.length < 10) {
            setError('messageError', 'Message must be at least 10 characters.');
            isValid = false;
        }

        // 3. Image Extension & Size Check
        if (imageInput.files[0]) {
            const file = imageInput.files[0];
            const allowed = ['jpg', 'jpeg', 'png', 'webp'];
            if (!allowed.includes(getExt(file.name))) {
                setError('imageError', 'Allowed images: jpg, jpeg, png, webp');
                isValid = false;
            } else if (file.size > maxSize) {
                setError('imageError', 'Image must be under 5MB.');
                isValid = false;
            }
        }

        // 4. PDF Extension & Type Check
        if (pdfInput.files[0]) {
            const file = pdfInput.files[0];
            if (getExt(file.name) !== 'pdf' || file.type !== 'application/pdf') {
                setError('pdfError', 'Only valid .pdf files are allowed.');
                isValid = false;
            } else if (file.size > maxSize) {
                setError('pdfError', 'PDF must be under 5MB.');
                isValid = false;
            }
        }

        if (galleryInput.files.length > 0) {
            for (let i = 0; i < galleryInput.files.length; i++) {
                const file = galleryInput.files[i];
                if (file.size > 5 * 1024 * 1024) {
                    setError('multipleError', `File ${file.name} is too large (Max 5MB).`);
                    isValid = false;
                }
            }
        }

        if (!isValid) {
            event.preventDefault();
        } else {
            submitBtn.disabled = true;
            submitBtn.textContent = 'Processing...';
        }
    });

    function setError(id, msg) {
        document.getElementById(id).textContent = msg;
    }
});
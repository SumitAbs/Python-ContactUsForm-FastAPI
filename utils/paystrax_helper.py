import json
from urllib.parse import urlencode
from urllib.request import build_opener, Request, HTTPHandler
from urllib.error import HTTPError, URLError

def send_payment_request(card_data: dict):
    """
    Sends payment data to PAYSTRAX test gateway using urllib.
    This helper handles the server-to-server communication.
    """
    url = "https://eu-test.oppwa.com/v1/payments"
    
    # Mapping the form data to Paystrax/Oppwa parameters
    payload = {
        'entityId': '8ac7a4c86a304582016a30b41682019b',
        'amount': card_data['amount'],
        'currency': 'EUR', # Fixed as per initial requirement
        'paymentBrand': card_data['paymentBrand'],
        'paymentType': 'DB',
        'card.number': card_data['number'],
        'card.holder': card_data['holder'],
        'card.expiryMonth': card_data['expiryMonth'],
        'card.expiryYear': card_data['expiryYear'],
        'card.cvv': card_data['cvv']
    }
    
    try:
        opener = build_opener(HTTPHandler)
        request_obj = Request(url, data=urlencode(payload).encode('utf-8'))
        # Using the provided Bearer Token
        request_obj.add_header('Authorization', 'Bearer OGFjN2E0Yzg2YTMwNDU4MjAxNmEzMGI0MTZlMjAxOWZ8QmJkdXdacGg5TUhMbTV0dzplbkw=')
        request_obj.get_method = lambda: 'POST'
        
        response = opener.open(request_obj)
        return json.loads(response.read())
    except HTTPError as e:
        return json.loads(e.read())
    except URLError as e:
        return {"error": str(e.reason)}
    

def send_3ds_request(card_data: dict, callback_url: str):
    """
    Initiates a 3D Secure authentication request to the Paystrax gateway.
    """
    url = "https://eu-test.oppwa.com/v1/threeDSecure"
    
    # Constructing the payload using transaction and browser data
    payload = {
        'entityId': '8ac7a4c86a304582016a30b41682019b', # Sandbox Entity ID
        'amount': card_data.get('amount'),
        'currency': 'EUR',
        'paymentBrand': card_data.get('paymentBrand'),
        'merchantTransactionId': card_data.get('merchantTransactionId', 'ORD-99234'),
        'transactionCategory': 'EC',
        'card.holder': card_data.get('holder'),
        'card.number': card_data.get('number'),
        'card.expiryMonth': card_data.get('expiryMonth'),
        'card.expiryYear': card_data.get('expiryYear'),
        'card.cvv': card_data.get('cvv'),
        'shopperResultUrl': callback_url,  # URL where the bank redirects after OTP
        'testMode': 'EXTERNAL',
        # Browser fingerprints are mandatory for 3DS verification
        'customer.browser.acceptHeader': 'text/html',
        'customer.browser.userAgent': 'Mozilla/5.0',
        'customer.browser.challengeWindow': '4'
    }

    try:
        opener = build_opener(HTTPHandler)
        # Encode payload to bytes for the POST request
        request_obj = Request(url, data=urlencode(payload).encode('utf-8'))
        # Add Authorization header with Bearer Token
        request_obj.add_header('Authorization', 'Bearer OGFjN2E0Yzg2YTMwNDU4MjAxNmEzMGI0MTZlMjAxOWZ8QmJkdXdacGg5TUhMbTV0dzplbkw=')
        request_obj.get_method = lambda: 'POST'
        
        with opener.open(request_obj) as response:
            return json.loads(response.read())
            
    except HTTPError as e:
        # Handling API level errors
        return json.loads(e.read())
    except URLError as e:
        # Handling network level errors
        return {"error": str(e.reason)}